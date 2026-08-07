"""
smoke_test.py — read-only check that ADB can see BlueStacks, take a
screenshot, and OCR it. No taps, no game state changes. Run this BEFORE
`python main.py --map`, so you're debugging "can I even see the screen"
separately from "can the agent play the game."

Run from the repo root: python tests/smoke_test.py
"""
import subprocess

import src.core.config as config
from src.device.device import get_current_app, screencap
from src.core.qa_common import ocr_all

print(f"ADB_PATH      : {config.ADB_PATH}")
print(f"DEVICE_SERIAL : {config.DEVICE_SERIAL or '(blank -> only connected device)'}")
print(f"GAME_PACKAGE  : {config.GAME_PACKAGE}")
print()

print("Raw `adb devices` output:")
try:
    result = subprocess.run([config.ADB_PATH, "devices"], capture_output=True, timeout=10, text=True)
    print(result.stdout.strip() or "(empty stdout)")
    if result.stderr.strip():
        print(f"stderr: {result.stderr.strip()}")
except Exception as e:
    print(f"Could not even run adb: {e}")
print()

current_app = get_current_app()
print(f"Foreground app right now: {current_app}")
if config.GAME_PACKAGE.lower() not in (current_app or "").lower():
    print("  -> Bloons TD6 isn't in the foreground. Bring it to the front in "
          "BlueStacks before running the real pipeline (or launch_game() will do it).")

png = screencap("outputs/logs/smoke_test.png")
if not png:
    print("FAILED: screenshot came back empty -- check the adb connect step.")
else:
    print(f"Screenshot OK: {len(png)} bytes -> smoke_test.png")

tokens = ocr_all("outputs/logs/smoke_test.png")
print(f"OCR read {len(tokens)} text tokens. Sample: {tokens[:10]}")
if not tokens:
    print("  (0 tokens is EXPECTED if OCR=OFF was printed above -- perception "
          "falls back to the VLM in that case, which is a separate, working path.)")

if png:
    print("\nSmoke test PASSED -- ADB/screenshot pipeline can see BlueStacks.")
    if not tokens:
        print("Note: OCR is disabled (see 'OCR=OFF' above) -- install paddlepaddle "
              "later to enable it; not required to proceed.")
else:
    print("\nSmoke test FAILED -- fix ADB/screenshot before running main.py.")