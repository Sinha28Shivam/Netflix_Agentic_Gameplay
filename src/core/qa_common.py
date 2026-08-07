#!/usr/bin/env python3
"""
agents/qa_common.py - Shared perception, VLM location, OCR, logging, and
                      device-interaction utilities for all agents.

Key design decisions (from dev iteration):
  * All config (ADB path, API key, model) comes from config.py — never hardcoded.
  * vlm_locate() retries with failed-point avoidance so the model doesn't repeat
    the same wrong coordinate.
  * read_hud() provides semantic signals (cash / round) for verifying in-match actions.
  * screen_signature()/wait_for_change() give cheap screen-change detection.
  * record()/results_summary() accumulate PASS/FAIL/NOT_OBSERVED results across a run.
  * Every tap and model call is written to ./logs with a timestamped screenshot.
"""

import os
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")

import base64
import concurrent.futures
import datetime
import json
import math
import re
import shutil
import struct
import time
import traceback

try:
    from anthropic import Anthropic
except Exception as _anthropic_import_err:
    Anthropic = None
    print(f"WARNING: could not import the 'anthropic' package ({_anthropic_import_err}). "
          f"VLM calls will be disabled until you run: pip install -r requirements.txt")

import src.core.config as config

# ---------------------------------------------------------------- CLIENT
if not config.LLM_API_KEY:
    print("WARNING: no API key configured. Set LLM_API_KEY or ANTHROPIC_API_KEY as an env var.")

_base_url = (config.LLM_BASE_URL or "").strip()
if _base_url.rstrip("/").endswith("/v1"):
    # The anthropic SDK appends "/v1/messages" itself -- a base_url that
    # already ends in "/v1" doubles the path into ".../v1/v1/messages" and
    # 404s on every call. Strip it rather than fail silently on a very easy
    # mistake to make (plenty of other APIs DO expect "/v1" included).
    print(f"NOTE: stripping trailing '/v1' from LLM_BASE_URL ({_base_url!r}) "
          f"-- the anthropic SDK adds that itself.")
    _base_url = _base_url.rstrip("/")[: -len("/v1")]

client = None
if Anthropic and config.LLM_API_KEY:
    try:
        client = Anthropic(api_key=config.LLM_API_KEY, base_url=(_base_url or None),
                           timeout=45.0, max_retries=0)
    except Exception as _client_init_err:
        print(f"WARNING: failed to construct the Anthropic client ({_client_init_err}). "
              f"VLM calls will be disabled.")
elif not Anthropic:
    pass  # already warned above
elif not config.LLM_API_KEY:
    pass  # already warned above

VISION_MODEL  = config.VISION_MODEL
DECIDER_MODEL = config.DECIDER_MODEL


def client_ready() -> bool:
    return client is not None


# ---------------------------------------------------------------- LOGGING
LOG_DIR  = config.LOG_DIR
os.makedirs(LOG_DIR, exist_ok=True)
RUN_ID   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(LOG_DIR, f"run_{RUN_ID}.log")
_shot_seq = 0


def log(msg: str):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def save_shot(tag: str = "") -> str:
    """Archive the current screenshot into LOG_DIR for post-run review."""
    global _shot_seq
    _shot_seq += 1
    safe = re.sub(r"[^A-Za-z0-9_-]", "", tag)[:40]
    dst = os.path.join(LOG_DIR, f"{RUN_ID}_{_shot_seq:03d}_{safe}.png")
    try:
        shutil.copyfile("outputs/logs/current.png", dst)
    except OSError:
        pass
    return dst


# ---------------------------------------------------------------- OCR SETUP
try:
    from paddleocr import PaddleOCR
    # enable_mkldnn=False is required on paddlepaddle 3.x here: its PIR
    # (Program IR) executor combined with the oneDNN/MKL-DNN CPU backend
    # doesn't implement some ops PP-OCRv6's preprocessing uses (array-of-double
    # attributes in resize/interpolation), which throws
    # "NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
    # [pir::ArrayAttribute<pir::DoubleAttribute>]" on every single OCR call.
    # ocr_all()'s exception handling used to swallow this silently, making a
    # 100% broken OCR pipeline look identical to "OCR just sees nothing."
    #
    # text_detection_model_name / text_recognition_model_name pin the 'tiny'
    # PP-OCRv6 tier instead of the default 'medium' -- medium was taking
    # 25-75s PER CALL on this CPU, which (since ocr_all() gets called many
    # times per step) was the single dominant cost in the whole pipeline.
    # tiny trades some accuracy for a large speed win; see the O/0
    # normalization in read_hud() below for the one accuracy regression that
    # tradeoff introduced and how it's compensated for.
    try:
        _ocr = PaddleOCR(lang="en", use_textline_orientation=False,
                         use_doc_orientation_classify=False, use_doc_unwarping=False,
                         enable_mkldnn=False,
                         text_detection_model_name="PP-OCRv6_tiny_det",
                         text_recognition_model_name="PP-OCRv6_tiny_rec")
    except Exception:
        try:
            _ocr = PaddleOCR(lang="en", enable_mkldnn=False)
        except Exception:
            _ocr = PaddleOCR(lang="en")
    _OCR_METHOD = "predict" if hasattr(_ocr, "predict") else "ocr"
    print(f"OCR=on (api={_OCR_METHOD})")
except Exception as e:
    _ocr, _OCR_METHOD = None, None
    print(f"OCR=OFF ({e}) - VLM will carry perception.")


# ---------------------------------------------------------------- ADB (thin wrappers — device layer owns the real impl)
from src.device.device import (
    screencap, tap, back, swipe, drag,
    force_stop, launch_game, png_dims,
)


def redness(png_path: str, cx, cy, box: int = 70) -> float:
    """Fraction of strongly-RED pixels in a box around (cx, cy).
    Bloons paints an invalid placement footprint red — high value ⟹ invalid spot."""
    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB")
        w, h = im.size
        x0, y0 = max(0, int(cx - box)), max(0, int(cy - box))
        x1, y1 = min(w, int(cx + box)), min(h, int(cy + box))
        px = list(im.crop((x0, y0, x1, y1)).getdata())
        if not px:
            return 0.0
        red = sum(1 for r, g, b in px if r > 140 and r - g > 60 and r - b > 60)
        return red / len(px)
    except Exception as e:
        log(f"   [redness] could not sample: {e}")
        return 0.0


# ---------------------------------------------------------------- SCENARIO RESULTS
_RESULTS = []


def record(name: str, status: str, detail: str = "") -> str:
    """Record PASS / FAIL / NOT_OBSERVED / SKIP for a named test. Thread-safe enough for one run."""
    status = status.upper()
    _RESULTS.append((name, status, detail))
    log(f"[SCENARIO] {name}: {status}" + (f" - {detail}" if detail else ""))
    return status


def results_summary():
    if not _RESULTS:
        log("[SUMMARY] no scenarios recorded")
        return
    counts: dict = {}
    for _, s, _ in _RESULTS:
        counts[s] = counts.get(s, 0) + 1
    log("================= SCENARIO SUMMARY =================")
    for name, status, detail in _RESULTS:
        log(f"  {status:<13} {name}" + (f"  ({detail})" if detail else ""))
    tally = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    log(f"  ---- totals: {tally} ----")
    log("===================================================")


# ---------------------------------------------------------------- OCR HELPERS
def ocr_all(png_path: str = "outputs/logs/current.png") -> list:
    import time as _t
    _start = _t.time()

    # Cache keyed on (path, mtime): the SAME screenshot gets OCR'd many times
    # per step by different callers (_settle, solidly_in_match, _tag_scene,
    # find_text). OCR inference is ~25s on this CPU, so re-running it on an
    # unchanged file was the dominant time sink (7-8x per step). screencap()
    # overwrites current.png with a new mtime whenever a fresh shot is taken,
    # so a genuinely new frame busts the cache automatically; repeated reads of
    # the same frame return instantly.
    try:
        _mtime = os.path.getmtime(png_path)
    except OSError:
        _mtime = None
    _cache = globals().get("_ocr_cache")
    if _cache is not None and _mtime is not None and _cache.get("key") == (png_path, _mtime):
        return _cache["val"]

    if _ocr is None:
        if not globals().get("_ocr_none_logged"):
            globals()["_ocr_none_logged"] = True
            print("WARNING: ocr_all() called but _ocr is None (OCR init must have failed earlier).")
        return []
    try:
        if not os.path.exists(png_path) or os.path.getsize(png_path) < 100:
            if not globals().get("_ocr_badfile_logged"):
                globals()["_ocr_badfile_logged"] = True
                exists = os.path.exists(png_path)
                size = os.path.getsize(png_path) if exists else None
                print(f"WARNING: ocr_all() skipped -- exists={exists}, size={size} for {png_path!r}.")
            return []
    except OSError:
        return []
    try:
        result = _ocr.predict(png_path) if _OCR_METHOD == "predict" else _ocr.ocr(png_path)
    except Exception as _call_err:
        try:
            result = _ocr.ocr(png_path)
        except Exception as _fallback_err:
            if not globals().get("_ocr_call_error_logged"):
                globals()["_ocr_call_error_logged"] = True
                print(f"WARNING: ocr_all() call failed on both predict() and ocr() fallback. "
                      f"predict() error: {_call_err!r} | ocr() error: {_fallback_err!r}")
            return []
    out = []
    try:
        for res in (result or []):
            if hasattr(res, "get") and res.get("rec_texts") is not None:
                texts  = res.get("rec_texts") or []
                scores = res.get("rec_scores") or [1.0] * len(texts)
                polys  = res.get("rec_polys") or res.get("dt_polys") or []
                for t, s, p in zip(texts, scores, polys):
                    xs = [float(pt[0]) for pt in p]; ys = [float(pt[1]) for pt in p]
                    out.append({"text": str(t), "score": float(s),
                                "x": int(sum(xs)/len(xs)), "y": int(sum(ys)/len(ys))})
            else:
                for line in (res or []):
                    box, (t, s) = line[0], line[1]
                    xs = [float(pt[0]) for pt in box]; ys = [float(pt[1]) for pt in box]
                    out.append({"text": str(t), "score": float(s),
                                "x": int(sum(xs)/len(xs)), "y": int(sum(ys)/len(ys))})
    except Exception as _parse_err:
        global _ocr_parse_error_logged
        if not globals().get("_ocr_parse_error_logged"):
            _ocr_parse_error_logged = True
            try:
                sample = result[0] if result else None
                print(f"WARNING: ocr_all() failed to parse the OCR result ({_parse_err}). "
                      f"result type={type(result)}, first-item type={type(sample)}, "
                      f"first-item repr={repr(sample)[:500]}")
            except Exception:
                print(f"WARNING: ocr_all() failed to parse the OCR result ({_parse_err}).")
        log(f"   [ocr] parse-failed in {_t.time()-_start:.1f}s")
        return []
    if not out and not globals().get("_ocr_empty_logged"):
        globals()["_ocr_empty_logged"] = True
        try:
            print(f"NOTE: OCR ran but found zero text regions. "
                  f"raw result type={type(result)}, len={len(result) if result else 0}, "
                  f"first-item repr={repr(result[0])[:500] if result else None}")
        except Exception:
            pass

    globals()["_ocr_cache"] = {"key": (png_path, _mtime), "val": out}
    log(f"   [ocr] {len(out)} texts in {_t.time()-_start:.1f}s")
    return out


def find_text(png_path: str, target: str, threshold: float = 0.6):
    t = target.lower().replace(" ", "")
    for it in ocr_all(png_path):                                     # exact first
        if it["score"] >= threshold and it["text"].lower().replace(" ", "") == t:
            return (it["x"], it["y"])
    for it in ocr_all(png_path):                                     # guarded contains
        norm = it["text"].lower().replace(" ", "")
        if it["score"] >= threshold and (
            (len(t) >= 4 and t in norm) or (len(norm) >= 4 and norm in t)
        ):
            return (it["x"], it["y"])
    return None


def find_all(png_path: str, target: str, threshold: float = 0.6) -> list:
    t = target.lower().replace(" ", "")
    res = []
    for it in ocr_all(png_path):
        norm = it["text"].lower().replace(" ", "")
        if it["score"] >= threshold and (
            norm == t or (len(t) >= 4 and t in norm) or (len(norm) >= 4 and norm in t)
        ):
            res.append((it["x"], it["y"], it["text"]))
    return res


# ---------------------------------------------------------------- VLM (GPT-5 / Claude) LOCATOR
VISION_RETRY_COUNT        = 5
MIN_DISTANCE_FROM_FAILED  = 140
BORDER_MARGIN             = 25

# Hard, code-enforced wall-clock cap per VLM call. A single stalled call was
# observed hanging for 31+ minutes despite the client itself being configured
# with timeout=45.0 -- that config clearly isn't a reliable enough backstop
# on its own (whatever the underlying cause -- a stalled connection, an OS/
# network-level hiccup, or something else -- the client-level timeout did not
# bound it). This makes the actual wait time independent of that, using a
# separate thread with its own deadline that this call site simply stops
# waiting on once the deadline passes.
_VLM_CALL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
VLM_HARD_TIMEOUT_S = 60


def _call_vlm_with_hard_timeout(image_b64, width, height, description, avoid_text=""):
    """Same as calling _call_vlm() directly, but never blocks longer than
    VLM_HARD_TIMEOUT_S wall-clock seconds, regardless of what's actually
    stalling underneath. Raises TimeoutError past the cap, which the retry
    loop in vlm_locate() already catches and logs like any other attempt
    failure."""
    future = _VLM_CALL_EXECUTOR.submit(_call_vlm, image_b64, width, height, description, avoid_text)
    try:
        return future.result(timeout=VLM_HARD_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        future.cancel()  # best-effort; the underlying network call may still
                          # finish on its own thread eventually, but this
                          # call site stops waiting for it immediately
        raise TimeoutError(f"VLM call exceeded hard timeout of {VLM_HARD_TIMEOUT_S}s")


def _distance(p1, p2) -> float:
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def _coordinate_valid(x, y, width, height) -> bool:
    return x is not None and y is not None and 0 <= x < width and 0 <= y < height


def _too_close(point, failed_points) -> bool:
    return any(_distance(point, fp) < MIN_DISTANCE_FROM_FAILED for fp in failed_points)


def _extract_json_loose(response):
    """Tolerant JSON extraction: code fences, Python booleans, stray whitespace."""
    if response is None:
        return None
    response = str(response).strip().replace("```json", "").replace("```", "")
    m = re.search(r"\{[\s\S]*\}", response)
    if not m:
        return None
    txt = m.group().replace("\n", " ").replace("\t", " ")
    txt = txt.replace("True", "true").replace("False", "false")
    try:
        return json.loads(txt)
    except Exception:
        return None


def _call_vlm(image_b64: str, width: int, height: int,
              description: str, avoid_text: str = "") -> str:
    system_prompt = f"""
You are an expert visual localization model.

Image size: Width={width}, Height={height}

Your ONLY job is locating ONE object.

Rules:
- Only say {{"found": false}} if the object is genuinely absent from the image
  (e.g. you are asked for a "PLAY" button on a screen that has no such button
  at all). Do NOT say not-found merely because you are uncertain about a fine
  visual distinction (exact icon color, which of several similar-looking
  shop icons is "cheapest", a single vs. double arrow, etc).
- If something plausibly matches the description, return your best-effort
  CENTER pixel for it rather than refusing. A wrong or approximate guess
  costs nothing here — the calling system verifies every result and retries
  automatically with corrected guidance. A refusal, on the other hand, blocks
  all further progress with no way to recover. Given that asymmetry, prefer
  a reasonable guess over {{"found": false}} whenever you can see ANY
  plausible candidate.
- Return the CENTER pixel of the element.

For BUILDABLE GRASS:
- Must not be on the path, water, rocks, flowers, trees, existing monkeys, or map edge.
- Choose the centre of the largest clear buildable region.

Return ONLY JSON — no prose.
"""
    prompt = f"""
Locate: {description}

{avoid_text}

Return ONLY:
{{"found": true, "x": 123, "y": 456}}
or
{{"found": false}}
"""
    response = client.messages.create(
        model=DECIDER_MODEL,
        max_tokens=300,
        system=system_prompt,
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64,
                }},
            ]}
        ],
    )
    return response.content[0].text


def vlm_locate(png_path: str, description: str,
               avoid=None, retries: int = VISION_RETRY_COUNT):
    """
    Ask the VLM for the pixel centre of an element.
    Returns (x, y) or None. Every attempt is logged.

    Failed / rejected candidates are fed back into subsequent attempts so the
    model does not repeat the same wrong coordinate.
    """
    if client is None:
        log("   [vlm] client not initialized.")
        return None
    try:
        with open(png_path, "rb") as f:
            png = f.read()
    except OSError as ex:
        log(f"   [vlm] unable to read image: {ex}")
        return None
    if not png:
        log("   [vlm] empty image.")
        return None

    width, height = png_dims(png)
    image_b64 = base64.b64encode(png).decode()

    failed_points = []
    if avoid:
        for p in avoid:
            try:
                failed_points.append((int(p[0]), int(p[1])))
            except Exception:
                pass

    log(f"   [vlm] looking for: {description[:80]}")

    for attempt in range(retries):
        avoid_text = ""
        if failed_points:
            avoid_text = "Previous locations failed. Do NOT return locations close to:\n"
            avoid_text += "\n".join(f"- ({x},{y})" for x, y in failed_points)
            avoid_text += "\n\nStay at least 150 pixels away.\n"
        try:
            raw = _call_vlm_with_hard_timeout(image_b64, width, height, description, avoid_text)
            data = _extract_json_loose(raw)
            if data is None:
                log(f"   [vlm] attempt {attempt+1}: invalid JSON.")
                continue
            if not data.get("found", False):
                log(f"   [vlm] attempt {attempt+1}: object not found.")
                continue
            try:
                x, y = int(round(float(data["x"]))), int(round(float(data["y"])))
            except Exception:
                log(f"   [vlm] attempt {attempt+1}: invalid coordinates.")
                continue
            if not _coordinate_valid(x, y, width, height):
                log(f"   [vlm] attempt {attempt+1}: outside image.")
                continue
            if _too_close((x, y), failed_points):
                log(f"   [vlm] attempt {attempt+1}: ({x},{y}) too close to previous failure.")
                continue
            if (x < BORDER_MARGIN or y < BORDER_MARGIN or
                    x > width - BORDER_MARGIN or y > height - BORDER_MARGIN):
                log(f"   [vlm] attempt {attempt+1}: candidate rejected (border).")
                failed_points.append((x, y))
                continue
            log(f"   [vlm] '{description[:40]}...' -> ({x},{y})")
            return (x, y)
        except Exception as ex:
            log(f"   [vlm] attempt {attempt+1} failed: {ex}")
            traceback.print_exc()
            time.sleep(0.6)

    log(f"   [vlm] unable to locate: {description[:60]}...")
    return None


def vlm_locate_precise(png_path: str, description: str, avoid=None,
                       retries: int = VISION_RETRY_COUNT,
                       crop_w: int = 820, crop_h: int = 560, zoom: int = 2):
    """Coarse-to-fine locate for SMALL targets (shop icons, tiny buttons).

    Absolute-pixel VLM localization is imprecise for a small element inside a
    large screenshot -- e.g. a ~130 px tower icon near the right edge of a
    2400 px-wide frame is routinely returned ~250 px off, landing in the panel
    border so the tap selects nothing. This does a normal locate to get a rough
    point, then crops a window around it, upscales the crop (so the target is
    now large), and re-locates INSIDE the crop for pixel accuracy, mapping the
    refined point back to full-image coordinates.

    Falls back to the coarse point if the refine step can't improve it, so it is
    always at least as good as vlm_locate(). No hardcoded coordinates.
    """
    coarse = vlm_locate(png_path, description, avoid=avoid, retries=retries)
    if not coarse:
        return None
    try:
        import io
        from PIL import Image
        img = Image.open(png_path).convert("RGB")
        W, H = img.size
        cx, cy = coarse
        # Center a crop on the coarse point, clamped to the image.
        x0 = max(0, min(cx - crop_w // 2, W - crop_w)) if W > crop_w else 0
        y0 = max(0, min(cy - crop_h // 2, H - crop_h)) if H > crop_h else 0
        cw = min(crop_w, W - x0)
        ch = min(crop_h, H - y0)
        crop = img.crop((x0, y0, x0 + cw, y0 + ch)).resize(
            (cw * zoom, ch * zoom), Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        raw = _call_vlm_with_hard_timeout(b64, cw * zoom, ch * zoom, description, "")
        data = _extract_json_loose(raw)
        if data and data.get("found") and "x" in data and "y" in data:
            rx = int(round(x0 + float(data["x"]) / zoom))
            ry = int(round(y0 + float(data["y"]) / zoom))
            if _coordinate_valid(rx, ry, W, H):
                log(f"   [vlm] refined ({cx},{cy}) -> ({rx},{ry})")
                return (rx, ry)
    except Exception as ex:
        log(f"   [vlm] refine step failed ({ex}); using coarse point {coarse}")
    return coarse


# ---------------------------------------------------------------- LLM TEXT HELPER
def ask_llm(prompt: str, model: str = None, max_tokens: int = 900) -> str:
    if client is None:
        return ""
    try:
        resp = client.messages.create(
            model=model or DECIDER_MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}])
        return resp.content[0].text or ""
    except Exception:
        return ""


def _extract_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e+1])


# ---------------------------------------------------------------- HUD / SEMANTIC READS
def _generic_read_hud(png_path: str = "outputs/logs/current.png") -> dict:
    """Best-effort cash / round from the HUD — used to verify in-match actions.

    NOTE on cash: the player's wallet readout in this game's in-match HUD is a
    coin ICON plus a bare number (e.g. "650") -- it does NOT have a literal
    '$' character. Only the shop's tower price tags ("$170", "$460", ...) do.
    Requiring '$' here would either never match the real wallet number, or --
    now that the pipeline reaches a real match with the shop column visible --
    latch onto a shop price instead of the player's actual cash. So cash is
    identified by being a bare 2-6 digit number sitting in the top-left HUD
    strip (where lives+cash live), not by the presence of '$'.
    """
    cash = rnd = lives = None
    try:
        with open(png_path, "rb") as f:
            width, height = png_dims(f.read())
    except Exception:
        width, height = None, None

    items = ocr_all(png_path)

    def _fix_o_zero(s: str) -> str:
        # OCR (especially the faster 'tiny' model) frequently reads the digit
        # '0' as the letter 'O' on this game's bold numeral font -- "1/4O"
        # instead of "1/40", "$65O" instead of "$650". Left alone, every
        # regex below that requires pure digits silently rejects these
        # legitimate readings, and read_hud() falls back to whatever OTHER
        # token happens to be all-digits in the same strip (e.g. picking up
        # the lives count instead of cash, or never finding a round number
        # at all). Only substitute 'O' when it's adjacent to digits, so real
        # words containing 'O' elsewhere in a token aren't corrupted.
        return re.sub(r"(?<=\d)O|O(?=\d)", "0", s)

    candidates = []
    for it in items:
        t = it["text"].replace(",", "").strip()
        t = re.sub(r"^\D+", "", t)  # strip a stray leading symbol (OCR sometimes
                                     # renders the coin icon as a literal '$')
        t = _fix_o_zero(t)
        if not re.fullmatch(r"\d{2,6}", t):
            continue
        if width and height and (it["x"] > width * 0.35 or it["y"] > height * 0.18):
            continue  # outside the top-left HUD strip -> a shop price or other number
        candidates.append((it["x"], int(t)))
    if candidates:
        # Lives sits leftmost (next to the heart icon), cash sits to its right
        # (next to the coin icon) -- take the rightmost candidate in the strip.
        candidates.sort()
        cash = candidates[-1][1]

    for it in items:
        t = _fix_o_zero(it["text"].replace(",", ""))
        m2 = re.search(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b", t)
        if not (m2 and int(m2.group(2)) >= 20):
            continue
        if width and height and it["y"] > height * 0.18:
            continue  # not in the top HUD strip -- likely incidental digits in
                      # body/rules text (e.g. "round 40", "200 lives" on a
                      # difficulty info screen), not the real round counter
        rnd = int(m2.group(1))
        break

    return {"cash": cash, "round": rnd, "lives": lives}


# ---------------------------------------------------------------- SCREEN-CHANGE DETECTION
def _pixel_hash(png_path: str, hash_size: int = 8) -> int:
    """Cheap perceptual hash (average hash) of the screenshot's pixels.

    OCR-only screen-change detection misses real navigation on stylized game
    UI (bold cartoon fonts, icon-heavy screens) where PaddleOCR reads the same
    handful of tokens -- or nothing at all -- on two visually distinct screens
    (e.g. BTD6's home screen vs. its map-select carousel). This hash gives an
    independent, text-free signal: downsize to a tiny grayscale thumbnail and
    encode each pixel as above/below the average brightness. Two genuinely
    different screens produce very different bit patterns; the same screen
    (even mid-animation) stays close.
    """
    try:
        from PIL import Image
        img = Image.open(png_path).convert("L").resize((hash_size, hash_size), Image.LANCZOS)
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = 0
        for p in pixels:
            bits = (bits << 1) | (1 if p >= avg else 0)
        return bits
    except Exception:
        return 0


def _pixel_hash_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


PIXEL_HASH_CHANGE_THRESHOLD = 6   # out of 64 bits (8x8) -- tuned for a clear navigation, not animation jitter


def screen_signature(png_path: str = "outputs/logs/current.png"):
    """(ocr_token_set, pixel_hash) -- two independent change signals so a real
    navigation is still caught even on screens OCR can't read well."""
    ocr_sig = frozenset(t.lower() for t in clean_tokens(ocr_all(png_path), cap=30))
    px_sig = _pixel_hash(png_path)
    return (ocr_sig, px_sig)


def screen_changed(before_sig, after_sig, min_diff: int = 2) -> bool:
    before_ocr, before_px = before_sig
    after_ocr, after_px = after_sig
    if len(before_ocr.symmetric_difference(after_ocr)) >= min_diff:
        return True
    return _pixel_hash_distance(before_px, after_px) >= PIXEL_HASH_CHANGE_THRESHOLD


def wait_for_change(before_sig, timeout: int = 8, poll: float = 1.5, settle_reads: int = 2) -> bool:
    """Poll until the screen's word-set changes AND stays stable for `settle_reads`
    consecutive reads, or timeout. Returns True only on a real, settled change.

    A single-read diff is not enough: many screens (e.g. the BTD6 home screen)
    keep fading in new buttons/labels for a second or two after they first
    appear. Requiring the new signature to hold steady across two spaced reads
    filters that out. The polling loop uses ONLY the pixel hash (no OCR) for
    each read, since OCR inference is slow enough to balloon a nominal timeout
    into minutes of real wall-clock time.
    """
    import time as _t
    _start = _t.time()
    before_px = before_sig[1] if isinstance(before_sig, tuple) else before_sig
    deadline = time.time() + timeout
    last_px = None
    stable_reads = 0
    polls = 0
    while time.time() < deadline:
        time.sleep(poll)
        screencap("outputs/logs/current.png")
        cur_px = _pixel_hash("outputs/logs/current.png")
        polls += 1
        dist = _pixel_hash_distance(before_px, cur_px)
        if dist < PIXEL_HASH_CHANGE_THRESHOLD:
            last_px = None
            stable_reads = 0
            continue
        if last_px is not None and _pixel_hash_distance(last_px, cur_px) < PIXEL_HASH_CHANGE_THRESHOLD:
            stable_reads += 1
        else:
            stable_reads = 1
        last_px = cur_px
        if stable_reads >= settle_reads:
            log(f"   [wait_for_change] changed after {polls} polls, {_t.time()-_start:.1f}s")
            return True
    log(f"   [wait_for_change] NO change in {polls} polls, {_t.time()-_start:.1f}s (timeout={timeout}s)")
    return False

# ---- Condition-driven waits (no hardcoded delays) ----
# These end on a CONDITION. The *_TIMEOUT_S values are FAILSAFES only — they
# fire solely when a screen is genuinely stuck, so nothing hangs forever. Kept
# deliberately short; they are not the primary pacing.
STABLE_TIMEOUT_S  = 12
LOADING_TIMEOUT_S = 30
STABLE_POLL_S     = 0.5


def wait_stable(max_wait: int = STABLE_TIMEOUT_S, stable_reads: int = 2,
                poll: float = STABLE_POLL_S) -> bool:
    """Return the moment the screen stops changing (pixel hash steady for
    `stable_reads` reads). No fixed floor: a static screen resolves in ~2 reads,
    a transition ends exactly when it ends. max_wait is only a failsafe cap."""
    deadline = time.time() + max_wait
    last, stable = None, 0
    while time.time() < deadline:
        screencap("outputs/logs/current.png")
        h = _pixel_hash("outputs/logs/current.png")
        if last is not None and _pixel_hash_distance(last, h) < PIXEL_HASH_CHANGE_THRESHOLD:
            stable += 1
        else:
            stable = 1
        last = h
        if stable >= stable_reads:
            return True
        time.sleep(poll)
    return False


def wait_not_loading(max_wait: int = LOADING_TIMEOUT_S) -> list:
    """If a loading screen is showing, wait until it clears (condition), then
    return the settled tokens. Failsafe-capped, not clock-paced."""
    deadline = time.time() + max_wait
    toks = clean_tokens(ocr_all("outputs/logs/current.png"))
    while is_loading(toks) and time.time() < deadline:
        time.sleep(1.0)
        screencap("outputs/logs/current.png")
        toks = clean_tokens(ocr_all("outputs/logs/current.png"))
    return toks
# ---------------------------------------------------------------- TEXT / SCENE HELPERS
def clean_tokens(ocr_items: list, min_len: int = 2, cap: int = 12) -> list:
    seen, toks = set(), []
    for it in ocr_items:
        t = it["text"].strip()
        low = t.lower()
        if len(low) < min_len or re.match(r"^[\d.,:%/x-]+$", low) or low in seen:
            continue
        seen.add(low)
        toks.append(t)
        if len(toks) >= cap:
            break
    return toks


def screen_id(scene: str, tokens: list, png_path: str = None) -> str:
    import hashlib
    key = scene + "|" + "|".join(sorted(t.lower() for t in tokens)[:8])
    if png_path and len(tokens) < 3:
        # OCR alone can't distinguish real screens once it reads few/no tokens
        # (some games' stylized fonts are effectively unreadable to PaddleOCR,
        # e.g. BTD6's bold cartoon UI font -- it can legitimately return []
        # on every single screen of a walkthrough). Without this, every such
        # screen hashes to scene + "" -> the SAME node id, so a whole
        # walkthrough silently collapses into one node with zero edges even
        # though navigation itself succeeded at every step. Folding in a
        # coarse pixel hash restores the ability to tell screens apart.
        try:
            key += "|" + hex(_pixel_hash(png_path))
        except Exception:
            pass
    return scene + "_" + hashlib.md5(key.encode()).hexdigest()[:8]


def candidate_labels(ocr_items: list, max_branch: int = 8) -> list:
    BLOCK = ("logout", "log out", "sign out", "delete", "purchase", "buy")
    out = []
    for t in clean_tokens(ocr_items, cap=40):
        if any(b in t.lower() for b in BLOCK):
            continue
        out.append(t)
        if len(out) >= max_branch:
            break
    return out


def is_loading(tokens) -> bool:
    if not tokens:
        return False
    blob = " ".join(str(t) for t in tokens).lower()
    if any(b in blob for b in ("start", "play", "go", "begin", "continue")):
        if not any(l in blob for l in ("loading...", "generating world", "building terrain")):
            return False
    if re.search(r"\d+%", blob) or re.search(r"step \d+ of \d+", blob):
        return True
    return any(k in blob for k in (
        "loading", "downloading", "summoning", "collecting",
        "unleashing", "preparing", "waking", "training",
        "generating world", "building terrain", "stay under water",
        "right tool for the job", "chopping wood"))


# ---------------------------------------------------------------- POPUP / MATCH-STATE HELPERS
_AFFIRM    = ["OK", "YES", "CONFIRM", "ACCEPT", "CLAIM", "COLLECT", "GOT IT", "CLOSE"]
_NEGATIVE  = ["CANCEL", "NO", "QUIT", "EXIT"]


def read_hud(png_path: str = "outputs/logs/current.png") -> dict:
    """Dispatcher: interpret the HUD via the ACTIVE game (so a game can override
    parsing). Defaults to the engine's generic reader. Bloons uses the generic
    path, so its behavior is unchanged."""
    from src.core.active_game import GAME
    return GAME.read_hud(png_path)


def _generic_on_main_menu(png: str = "outputs/logs/current.png") -> bool:
    """Genre-neutral 'are we on a menu?' heuristic. A game overrides
    GameProfile.on_main_menu for its own menu vocabulary."""
    blob = " ".join(t.lower() for t in clean_tokens(ocr_all(png), cap=40))
    return any(w in blob for w in (
        "play", "start", "settings", "main menu", "home", "quit", "exit",
        "continue", "options",
    ))


def _on_main_menu(png: str = "outputs/logs/current.png") -> bool:
    """Dispatcher: menu detection via the ACTIVE game."""
    from src.core.active_game import GAME
    return GAME.on_main_menu(png)


def in_match(png: str = "outputs/logs/current.png") -> bool:
    screencap(png)
    return read_hud(png).get("round") is not None and not _on_main_menu(png)


def solidly_in_match(png: str = "outputs/logs/current.png") -> bool:
    screencap(png)
    hud = read_hud(png)
    on_menu = _on_main_menu(png)
    result = (hud.get("round") is not None and
              hud.get("cash") is not None and
              not on_menu)
    if not result:
        raw_items = ocr_all(png)
        log(f"NOTE: solidly_in_match() returned False -- hud={hud}, "
            f"_on_main_menu={on_menu}, raw OCR items: "
            f"{[(it['text'], it['x'], it['y']) for it in raw_items][:30]}")
    return result


def _looks_like_dialog(tokens: list) -> bool:
    # If active game profile specifies that this token set belongs to a normal game screen, ignore
    from src.core.active_game import GAME
    if hasattr(GAME, "is_normal_screen") and GAME.is_normal_screen(tokens):
        return False

    upp  = {t.upper() for t in tokens}
    blob = " ".join(tokens).lower()
    pair    = any(a in upp for a in _AFFIRM) and any(n in upp for n in _NEGATIVE)
    reward  = ("claim reward" in blob) or ("free gift" in blob) or ("collect reward" in blob)
    overwrite = ("overwrite" in blob) or ("are you sure" in blob)
    interstitial = ("level up" in blob) or ("new hero" in blob) or ("unlocked" in blob)
    return pair or reward or overwrite or interstitial


def clear_popups(goal: str, max_rounds: int = 4) -> bool:
    """
    Handle a blocking dialog ONLY when one is actually present. Returns True if
    at least one popup was cleared. Does NOT tap on normal (non-dialog) screens.
    """
    cleared = False
    for _ in range(max_rounds):
        screencap("outputs/logs/current.png")
        toks = clean_tokens(ocr_all("outputs/logs/current.png"), cap=40)
        if not _looks_like_dialog(toks):
            break
        target = None
        for word in _AFFIRM:
            target = find_text("outputs/logs/current.png", word)
            if target:
                log(f"   dialog confirm button via OCR: '{word}'")
                break
        if not target:
            # Full-screen interstitials (e.g. "LEVEL UP!") often have no
            # labeled button at all -- they just need any tap to dismiss.
            # This only fires once _looks_like_dialog() has ALREADY confirmed
            # something dialog-like is genuinely showing, so it doesn't risk
            # misfiring a blind center-tap on ordinary gameplay screens.
            try:
                with open("outputs/logs/current.png", "rb") as f:
                    w, h = png_dims(f.read())
            except Exception:
                w, h = 1080, 1920
            target = (w // 2, h // 2)
            log("   no labeled confirm button found; tapping screen center to dismiss interstitial")
        before = screen_signature()
        tap(*target, f"dialog -> continue ({goal})")
        wait_for_change(before, timeout=6)
        log(f"   handled a popup (continuing toward: {goal})")
        cleared = True
    return cleared