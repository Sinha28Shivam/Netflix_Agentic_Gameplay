"""
src/device/appium_utils.py — Appium backend for the device layer.

Mirrors the PUBLIC interface of src/device/android/adb_utils.py so it can be
swapped in behind src/device/device.py (selected by config.EXECUTION_MODE)
without touching qa_common / executor / orchestrator. Same function names,
same coordinate contract.

Design notes (see the migration plan in the plan file):

  * COORDINATE CONTRACT — every public coordinate (tap/swipe/drag input, and
    get_screen_size output) is in SCREENSHOT-PIXEL space, exactly as with ADB
    (where `screencap` and `input tap` share the device framebuffer grid). The
    VLM returns coordinates in that space. Appium W3C pointer actions, however,
    use the driver's window coordinate space, which MAY differ from the
    screenshot pixel size (scaling / insets). `_to_action()` applies the one
    scale factor `window / screenshot` at the action boundary, so VLM-correct
    points land correctly. When the two spaces match (the common case) the
    scale is 1.0 and behaviour is identical to ADB.

  * SCREENSHOT — captured in-memory via `get_screenshot_as_base64()` (fast; no
    SD-card write+pull), decoded, and written to the same PNG path the whole
    perception stack (vlm_locate / read_hud / redness / OCR) already reads.

  * DRAG — a real W3C press-hold-carry-release: pointer_down -> pause(hold) ->
    stepped pointer_move over ~duration -> pause -> pointer_up. This is what
    Bloons tower placement needs and is more reliable than an ADB swipe.

  * PERF — `run_adb` still shells out to the adb binary, so perf_utils.py and
    recovery_agent's raw adb calls keep working unchanged under Appium.

All appium/selenium imports are LAZY (inside functions) so importing this
module never requires the Appium client unless the appium backend is used.
"""

import base64
import time
import xml.etree.ElementTree as ET

import src.core.config as config
# adb helpers with no heavy deps — reused so perf/recovery keep working and we
# don't reimplement a pure-PNG header parser.
from src.device.android.adb_utils import png_dims, run_adb  # noqa: F401 (re-exported)

# ------------------------------------------------------------------
# Session + coordinate-scale state (module singletons)
# ------------------------------------------------------------------
_DRIVER = None
_SHOT_DIMS = None       # (w, h) of a screenshot, in pixels
_SCALE = None           # (sx, sy) screenshot-pixel -> action(window) space
_BLACK_CHECKED = False


def get_driver():
    """Lazily build and cache the Appium UiAutomator2 session."""
    global _DRIVER
    if _DRIVER is not None:
        try:
            if _DRIVER.session_id is not None:
                return _DRIVER
        except Exception:
            _DRIVER = None
    from appium import webdriver
    from appium.options.android import UiAutomator2Options

    opts = UiAutomator2Options()
    opts.platform_name = config.APPIUM_PLATFORM_NAME
    opts.automation_name = "UiAutomator2"
    if config.DEVICE_SERIAL:
        opts.udid = config.DEVICE_SERIAL
    pkg = _active_pkg()
    opts.app_package = pkg
    if config.GAME_ACTIVITY:
        opts.app_activity = config.GAME_ACTIVITY
    opts.no_reset = True            # don't wipe app state between sessions
    opts.new_command_timeout = 3600  # keep the session alive through long OCR waits
    print(f"Appium: connecting to {config.APPIUM_SERVER_URL} "
          f"({config.APPIUM_PLATFORM_NAME}, {pkg})")
    _DRIVER = webdriver.Remote(config.APPIUM_SERVER_URL, options=opts)
    return _DRIVER


def quit_driver():
    """Tear down the session (safe to call even if never started)."""
    global _DRIVER, _SHOT_DIMS, _SCALE, _BLACK_CHECKED
    if _DRIVER is not None:
        try:
            _DRIVER.quit()
        except Exception:
            pass
    _DRIVER = _SHOT_DIMS = _SCALE = None
    _BLACK_CHECKED = False


# ------------------------------------------------------------------
# Coordinate scaling (screenshot-pixel space -> action/window space)
# ------------------------------------------------------------------
def _shot_dims():
    global _SHOT_DIMS
    if _SHOT_DIMS is None:
        png = base64.b64decode(get_driver().get_screenshot_as_base64())
        _SHOT_DIMS = png_dims(png)
    return _SHOT_DIMS


def _action_scale():
    """(sx, sy) to convert a screenshot-pixel coordinate into the coordinate
    space Appium pointer actions expect. 1.0 when the two spaces match."""
    global _SCALE
    if _SCALE is None:
        try:
            ws = get_driver().get_window_size()
            sw, sh = _shot_dims()
            sx = ws["width"] / sw if sw else 1.0
            sy = ws["height"] / sh if sh else 1.0
            _SCALE = (sx, sy)
            if abs(sx - 1.0) > 0.01 or abs(sy - 1.0) > 0.01:
                print(f"WARN: Appium coordinate scale != 1: screenshot={sw}x{sh}, "
                      f"window={ws['width']}x{ws['height']} -> scale=({sx:.3f},{sy:.3f}). "
                      f"Coordinates will be mapped; verify placement lands on target.")
        except Exception as e:
            print(f"WARN: could not compute Appium coordinate scale ({e}); assuming 1:1")
            _SCALE = (1.0, 1.0)
    return _SCALE


def _to_action(x, y):
    sx, sy = _action_scale()
    return int(round(x * sx)), int(round(y * sy))


# ------------------------------------------------------------------
# Screenshot
# ------------------------------------------------------------------
def get_screenshot_base64() -> str:
    return get_driver().get_screenshot_as_base64()


def screencap(path: str = "outputs/logs/current.png") -> bytes:
    """Grab the screen in-memory and write a device-native PNG to `path`. Fallback to ADB on session loss."""
    global _DRIVER
    raw = b""
    try:
        raw = base64.b64decode(get_driver().get_screenshot_as_base64())
    except Exception as e:
        print(f"WARN: appium screencap failed ({e}); using ADB fallback")
        _DRIVER = None
        from src.device.android import adb_utils
        return adb_utils.screencap(path)

    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError as e:
        print(f"WARN: appium screencap: could not write {path}: {e}")
        return b""
    _warn_if_black(raw)
    return raw


def _warn_if_black(png_bytes: bytes):
    """One-time check: Appium can return an all-black frame for GPU SurfaceView
    games. If so, the VLM would be fed a blank image -> garbage coordinates.
    Flag it loudly and point at the hybrid fallback."""
    global _BLACK_CHECKED
    if _BLACK_CHECKED or not png_bytes:
        return
    _BLACK_CHECKED = True
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(png_bytes)).convert("L").resize((32, 32))
        px = list(im.getdata())
        if px and (sum(px) / len(px)) < 6:  # near-uniformly black
            print("WARN: APPIUM SCREENSHOT LOOKS BLACK -- the game likely renders via a GPU "
                  "SurfaceView that UiAutomator2 can't capture. The VLM will hallucinate on "
                  "a blank frame. Fallback: use ADB for screenshots (hybrid) -- set "
                  "EXECUTION_MODE=adb for capture, or capture via adb screencap.")
    except Exception:
        pass


# ------------------------------------------------------------------
# UI text (view hierarchy) — analog of `uiautomator dump`
# ------------------------------------------------------------------
def get_ui_texts():
    """Visible text + content-desc labels from the Appium page source.
    (For a GPU-rendered game the hierarchy is largely empty — same as adb.)"""
    try:
        xml = get_driver().page_source
    except Exception as e:
        print(f"WARN: appium page_source failed: {e}")
        return []
    texts = []
    try:
        root = ET.fromstring(xml)
        for node in root.iter():
            for attr in ("text", "content-desc"):
                val = (node.attrib.get(attr) or "").strip()
                if val:
                    texts.append(val)
    except ET.ParseError:
        pass
    return texts


# ------------------------------------------------------------------
# App / process lifecycle
# ------------------------------------------------------------------
def get_current_app() -> str:
    try:
        return get_driver().current_package or ""
    except Exception:
        return ""


def _active_pkg() -> str:
    """Package of the active game, with a safe fallback to config."""
    try:
        from src.core.active_game import active_package
        return active_package()
    except Exception:
        return config.GAME_PACKAGE


def force_stop(pkg: str = None):
    pkg = pkg or _active_pkg()
    try:
        get_driver().terminate_app(pkg)
    except Exception as e:
        print(f"WARN: appium terminate_app({pkg}) failed: {e}")
    time.sleep(1)


def launch_game(pkg: str = None):
    pkg = pkg or _active_pkg()
    print(f"Appium launching {pkg}")
    try:
        get_driver().activate_app(pkg)
    except Exception as e:
        print(f"WARN: appium activate_app({pkg}) failed: {e}")
    time.sleep(5)


# ------------------------------------------------------------------
# Touch / gesture primitives (W3C pointer actions)
# ------------------------------------------------------------------
def _finger_actions():
    from selenium.webdriver.common.actions.action_builder import ActionBuilder
    from selenium.webdriver.common.actions.pointer_input import PointerInput
    from selenium.webdriver.common.actions import interaction
    finger = PointerInput(interaction.POINTER_TOUCH, "finger")
    return ActionBuilder(get_driver(), mouse=finger), finger


def tap(x, y, label: str = ""):
    global _DRIVER
    ax, ay = _to_action(x, y)
    if label:
        print(f"   TAP ({ax},{ay}) {label}")
    try:
        ab, _ = _finger_actions()
        a = ab.pointer_action
        a.move_to_location(ax, ay)
        a.pointer_down()
        a.pause(0.05)
        a.pointer_up()
        ab.perform()
        time.sleep(1.2)
    except Exception as e:
        print(f"WARN: appium tap failed ({e}); executing via ADB fallback")
        _DRIVER = None
        from src.device.android import adb_utils
        adb_utils.tap(x, y, label=label)


def text_input(text: str, label: str = ""):
    global _DRIVER
    if label:
        print(f"   TEXT INPUT '{text}' {label}")
    try:
        el = get_driver().switch_to.active_element
        if el:
            el.send_keys(text)
            time.sleep(0.8)
            return
    except Exception:
        pass
    from src.device.android import adb_utils
    adb_utils.text_input(text, label=label)


def back():
    global _DRIVER
    try:
        get_driver().back()
    except Exception as e:
        print(f"WARN: appium back() failed ({e}); executing via ADB fallback")
        _DRIVER = None
        from src.device.android import adb_utils
        adb_utils.back()
    time.sleep(0.5)


def swipe(x1, y1, x2, y2, duration_ms: int = 350, label: str = ""):
    global _DRIVER
    ax1, ay1 = _to_action(x1, y1)
    ax2, ay2 = _to_action(x2, y2)
    if label:
        print(f"   SWIPE ({ax1},{ay1})->({ax2},{ay2}) {label}")
    try:
        ab, _ = _finger_actions()
        a = ab.pointer_action
        a.move_to_location(ax1, ay1)
        a.pointer_down()
        a.pause(0.05)
        _stepped_move(a, ax1, ay1, ax2, ay2, duration_ms, steps=8)
        a.pointer_up()
        ab.perform()
        time.sleep(1.0)
    except Exception as e:
        print(f"WARN: appium swipe failed ({e}); executing via ADB fallback")
        _DRIVER = None
        from src.device.android import adb_utils
        adb_utils.swipe(x1, y1, x2, y2, duration_ms=duration_ms, label=label)


def drag(x1, y1, x2, y2, duration_ms: int = 1000, label: str = "",
         hold: bool = True, steps: int = 16, hold_ms: int = 250, settle_ms: int = 1200):
    """Press-and-HOLD, carry, release — the gesture Bloons placement needs.

    pointer_down (source) -> pause(hold_ms) -> stepped pointer_move to target
    over ~duration_ms -> short pause -> pointer_up. The hold makes the game
    'grab' the tower before it is carried. (`hold` kwarg kept for signature
    parity with the ADB backend; the appium gesture always holds.)
    """
    global _DRIVER
    ax1, ay1 = _to_action(x1, y1)
    ax2, ay2 = _to_action(x2, y2)
    if label:
        print(f"   DRAG ({ax1},{ay1})->({ax2},{ay2}) {label}")
    try:
        ab, _ = _finger_actions()
        a = ab.pointer_action
        a.move_to_location(ax1, ay1)
        a.pointer_down()
        a.pause(max(0, hold_ms) / 1000.0)          # grab the tower
        _stepped_move(a, ax1, ay1, ax2, ay2, duration_ms, steps=steps)
        a.pause(0.15)                               # settle on the drop spot
        a.pointer_up()
        ab.perform()
        time.sleep(settle_ms / 1000.0)
    except Exception as e:
        err_msg = str(e).split("\n")[0]
        print(f"WARN: Appium W3C drag failed ({err_msg}); executing via ADB fallback")
        from src.device.android import adb_utils
        adb_utils.drag(x1, y1, x2, y2, duration_ms=duration_ms, label=label)


def _stepped_move(pointer_action, x1, y1, x2, y2, duration_ms, steps):
    """Interpolated pointer_move so the carry is smooth over ~duration_ms —
    continuous movement games register far better than a single jump."""
    steps = max(1, int(steps))
    per_pause = (max(0, duration_ms) / 1000.0) / steps
    for i in range(1, steps + 1):
        xi = x1 + (x2 - x1) * i // steps
        yi = y1 + (y2 - y1) * i // steps
        pointer_action.move_to_location(int(xi), int(yi))
        if per_pause:
            pointer_action.pause(per_pause)


# ------------------------------------------------------------------
# Screen size + directional swipes (coords in SCREENSHOT-pixel space)
# ------------------------------------------------------------------
def get_screen_size():
    """Return SCREENSHOT-pixel dimensions (the coordinate space callers use),
    matching adb_utils.get_screen_size()'s contract."""
    try:
        return _shot_dims()
    except Exception:
        return (1080, 1920)


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


# ------------------------------------------------------------------
# Parity shims for the adb_utils surface
# ------------------------------------------------------------------
def _supports_motionevent() -> bool:
    """Unused by the appium drag (it uses W3C actions); present for interface
    parity with the adb backend."""
    return False
