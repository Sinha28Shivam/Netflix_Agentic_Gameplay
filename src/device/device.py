"""
src/device/device.py — device-backend router.

All agents import their device primitives from HERE (not directly from a
backend), so the action layer can be swapped between ADB and Appium with a
single config switch and no changes to callers.

    EXECUTION_MODE=adb     (default) -> src/device/android/adb_utils.py
    EXECUTION_MODE=appium            -> src/device/appium_utils.py

Both backends expose the identical function surface and coordinate contract
(screenshot-pixel space in, device action out), so this module just binds the
chosen backend's names. `run_adb` always resolves to the real adb binary
(the appium backend delegates to it), so perf sampling and recovery keep
working regardless of mode.
"""

import src.core.config as config

_BACKEND = (getattr(config, "EXECUTION_MODE", "adb") or "adb").strip().lower()

if _BACKEND == "appium":
    from src.device.appium_utils import (          # noqa: F401
        run_adb, screencap, get_screenshot_base64, png_dims,
        get_ui_texts, get_current_app, force_stop, launch_game,
        tap, back, swipe, drag, get_screen_size, text_input,
        swipe_left, swipe_right, swipe_up, swipe_down,
    )
    print("device backend: APPIUM")
else:
    from src.device.android.adb_utils import (      # noqa: F401
        run_adb, screencap, get_screenshot_base64, png_dims,
        get_ui_texts, get_current_app, force_stop, launch_game,
        tap, back, swipe, drag, get_screen_size, text_input,
        swipe_left, swipe_right, swipe_up, swipe_down,
    )

BACKEND = _BACKEND
