"""
device/adb_utils.py - ADB primitives used by all agents and qa_common.

Provides both the high-level helpers the original orchestrator/agents need
(get_screenshot_base64, get_ui_texts, launch_game …) AND the low-level
single-call wrappers qa_common uses (_adb, _adb_out, screencap, tap, etc.).
Everything is driven by config.py — no hardcoded paths here.
"""

import base64
import re
import subprocess
import struct
import xml.etree.ElementTree as ET
from typing import Tuple

import src.core.config as config


# ------------------------------------------------------------------
# Core ADB caller
# ------------------------------------------------------------------

def _adb_prefix():
    cmd = [config.ADB_PATH]
    if config.DEVICE_SERIAL:
        cmd += ["-s", config.DEVICE_SERIAL]
    return cmd


def run_adb(args, timeout=15) -> str:
    """Run `adb <args>` and return stdout as text."""
    cmd = _adb_prefix() + args
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="ignore").strip()
            if err:
                print(f"⚠ adb error ({' '.join(str(a) for a in cmd)}): {err}")
        return result.stdout.decode("utf-8", errors="ignore")
    except subprocess.TimeoutExpired:
        print(f"⚠ adb command timed out: {' '.join(str(a) for a in cmd)}")
        return ""
    except FileNotFoundError:
        raise RuntimeError(
            f"Could not find adb at '{config.ADB_PATH}'. "
            "Set ADB_PATH env var or add adb to PATH."
        )


def _adb_prefix_str() -> str:
    """String form of _adb_prefix() for the shell=True helpers below --
    _adb()/_adb_out() previously built their command as just
    f'"{ADB_PATH}" {cmd}', silently ignoring DEVICE_SERIAL. With exactly one
    device connected that's invisible; with two (e.g. BlueStacks +
    a leftover AVD) every call through _adb() fails with 'more than one
    device/emulator' -- which used to be swallowed along with the rest of
    stderr. tap/swipe/screencap/force_stop/launch_game all go through
    _adb(), so this bug silently broke nearly the whole action/perception
    path whenever more than one device was attached."""
    prefix = f'"{config.ADB_PATH}"'
    if config.DEVICE_SERIAL:
        prefix += f' -s {config.DEVICE_SERIAL}'
    return prefix


def _adb(cmd: str):
    """Shell helper used by qa_common (accepts a single string command)."""
    result = subprocess.run(
        f'{_adb_prefix_str()} {cmd}',
        shell=True, check=False, capture_output=True
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="ignore").strip()
        if err:
            print(f"⚠ adb error ({cmd}): {err}")


def _adb_out(cmd: str) -> str:
    """Shell helper returning stdout (used by qa_common)."""
    result = subprocess.run(
        f'{_adb_prefix_str()} {cmd}',
        shell=True, capture_output=True, text=True, check=False
    )
    if result.returncode != 0 and result.stderr.strip():
        print(f"⚠ adb error ({cmd}): {result.stderr.strip()}")
    return result.stdout


# ------------------------------------------------------------------
# Screenshot
# ------------------------------------------------------------------

def get_screenshot_base64() -> str:
    """Capture screenshot and return as base64 PNG string (for VisionAgent)."""
    cmd = _adb_prefix() + ["exec-out", "screencap", "-p"]
    result = subprocess.run(cmd, capture_output=True, timeout=15)
    if not result.stdout:
        err = result.stderr.decode("utf-8", errors="ignore").strip()
        print(f"⚠ screenshot came back empty" + (f": {err}" if err else " (no stderr -- check `adb devices`)"))
    return base64.b64encode(result.stdout).decode("utf-8")


def screencap(path: str = "outputs/logs/current.png") -> bytes:
    """Capture screenshot directly to a file (for qa_common / agents)."""
    _adb(f"exec-out screencap -p > {path}")
    try:
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            print(f"⚠ screencap wrote an empty file at {path} -- see any ⚠ adb error above")
        return data
    except OSError:
        print(f"⚠ screencap: {path} was never written -- see any ⚠ adb error above")
        return b""


def png_dims(png_bytes: bytes) -> Tuple[int, int]:
    """Return (width, height) from the PNG header bytes."""
    try:
        if png_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", png_bytes[16:24])
            return int(w), int(h)
    except Exception:
        pass
    return 2340, 1080


# ------------------------------------------------------------------
# UI text (uiautomator dump — original orchestrator path)
# ------------------------------------------------------------------

def get_ui_texts():
    """Dump the on-screen view hierarchy and return all visible text labels."""
    run_adb(["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"])
    raw_xml = run_adb(["shell", "cat", "/sdcard/window_dump.xml"])
    texts = []
    try:
        root = ET.fromstring(raw_xml)
        for node in root.iter("node"):
            text = node.attrib.get("text", "").strip()
            if text:
                texts.append(text)
    except ET.ParseError:
        pass
    return texts


# ------------------------------------------------------------------
# App / process helpers
# ------------------------------------------------------------------

def get_current_app() -> str:
    """Return the package name of the foreground app."""
    output = run_adb(["shell", "dumpsys", "window", "windows"])
    match = re.search(r"mCurrentFocus.*?\{.*?\s([\w.]+)/", output)
    return match.group(1) if match else ""


def _active_pkg() -> str:
    """Package of the active game, with a safe fallback to config. Lazy import
    keeps the low-level device layer free of an import-time dependency on the
    game registry."""
    try:
        from src.core.active_game import active_package
        return active_package()
    except Exception:
        return config.GAME_PACKAGE


def force_stop(pkg: str = None):
    pkg = pkg or _active_pkg()
    _adb(f"shell am force-stop {pkg}")
    import time; time.sleep(1)


def launch_game(pkg: str = None):
    pkg = pkg or _active_pkg()
    print(f"🚀 Launching {pkg}")
    if config.GAME_ACTIVITY:
        run_adb(["shell", "am", "start", "-n", f"{pkg}/{config.GAME_ACTIVITY}"])
    else:
        _adb(f"shell monkey -p {pkg} 1")
    import time; time.sleep(5)


# ------------------------------------------------------------------
# Touch / gesture primitives
# ------------------------------------------------------------------

def tap(x, y, label: str = ""):
    if label:
        print(f"   TAP ({int(x)},{int(y)}) {label}")
    _adb(f"shell input tap {int(x)} {int(y)}")
    import time; time.sleep(1.2)


def text_input(text: str, label: str = ""):
    if label:
        print(f"   TEXT INPUT '{text}' {label}")
    escaped = text.replace(" ", "%s")
    _adb(f"shell input text {escaped}")
    import time; time.sleep(0.8)


def back():
    _adb("shell input keyevent 4")
    import time; time.sleep(0.5)


def swipe(x1, y1, x2, y2, duration_ms: int = 350, label: str = ""):
    if label:
        print(f"   SWIPE ({int(x1)},{int(y1)})->({int(x2)},{int(y2)}) {label}")
    _adb(f"shell input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")
    import time; time.sleep(1.0)


def drag(x1, y1, x2, y2, duration_ms: int = 700, label: str = "",
         hold: bool = True, steps: int = 12, hold_ms: int = 450, settle_ms: int = 1200):
    """Pick-up-and-carry drag.

    Games like Bloons TD 6 register a tower placement only for a genuine
    press-and-HOLD followed by a slow move and release — a plain `input swipe`
    is too abrupt and is frequently ignored (the tower never drops, cash stays
    unchanged). So by default we synthesize the gesture with `input motionevent`:

        DOWN (source) -> hold -> stepped MOVEs -> short settle -> UP (target)

    The initial hold is what makes the game "grab" the tower before we carry it.
    If `hold=False` (or on a device whose `input` lacks the motionevent
    subcommand — API < 26), we fall back to the classic `input swipe`.
    """
    import time
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    if label:
        print(f"   DRAG ({x1},{y1})->({x2},{y2}) {label}")

    if hold and _supports_motionevent():
        _adb(f"shell input motionevent DOWN {x1} {y1}")
        time.sleep(hold_ms / 1000.0)                       # grab the tower
        steps = max(1, int(steps))
        for i in range(1, steps + 1):
            xi = x1 + (x2 - x1) * i // steps
            yi = y1 + (y2 - y1) * i // steps
            _adb(f"shell input motionevent MOVE {xi} {yi}")
            time.sleep(0.03)
        time.sleep(0.15)                                   # let the ghost settle on the drop spot
        _adb(f"shell input motionevent UP {x2} {y2}")
    else:
        _adb(f"shell input swipe {x1} {y1} {x2} {y2} {int(duration_ms)}")
    time.sleep(settle_ms / 1000.0)


_MOTIONEVENT_SUPPORTED = None


def _supports_motionevent() -> bool:
    """Cache whether `input motionevent` exists on this device (API >= 26).
    Falls back gracefully to `input swipe` when it doesn't."""
    global _MOTIONEVENT_SUPPORTED
    if _MOTIONEVENT_SUPPORTED is None:
        try:
            sdk = run_adb(["shell", "getprop", "ro.build.version.sdk"]).strip()
            _MOTIONEVENT_SUPPORTED = bool(sdk) and int(sdk) >= 26
        except Exception:
            _MOTIONEVENT_SUPPORTED = False
    return _MOTIONEVENT_SUPPORTED


def get_screen_size() -> Tuple[int, int]:
    output = run_adb(["shell", "wm", "size"])
    match = re.search(r"(\d+)x(\d+)", output)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1080, 1920


def swipe_left():
    w, h = get_screen_size()
    swipe(int(w * 0.8), int(h * 0.5), int(w * 0.2), int(h * 0.5))


def swipe_right():
    w, h = get_screen_size()
    swipe(int(w * 0.2), int(h * 0.5), int(w * 0.8), int(h * 0.5))


def swipe_up():
    w, h = get_screen_size()
    swipe(int(w * 0.5), int(h * 0.8), int(w * 0.5), int(h * 0.2))


def swipe_down():
    w, h = get_screen_size()
    swipe(int(w * 0.5), int(h * 0.2), int(w * 0.5), int(h * 0.8))