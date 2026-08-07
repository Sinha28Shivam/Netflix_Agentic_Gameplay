#!/usr/bin/env python3
"""
scripts/check_drag.py — quick ONE-SHOT drag-and-drop check on the live match.

Run this WHILE you are standing on the battlefield with cash to spend:

    python -m scripts.check_drag

It exercises the exact gameplay placement path (place_one): locate the Dart
Monkey + a grass spot with the VLM, perform the robust press-hold drag, and
report whether cash dropped (= a tower was really placed). Screenshots of each
attempt are written to outputs/logs/place1_*.png for inspection.

Prereqs: device on ADB, you are IN a match, and LLM_API_KEY is set (the VLM is
what finds the tower icon and the grass — the drag itself is free).
"""

import os
import sys

# Make 'src' importable whether run as `-m scripts.check_drag` or by path.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.qa_common import client_ready, screencap, read_hud, solidly_in_match
from src.agents.execution.executor_agent import place_one


def main():
    if not client_ready():
        raise SystemExit("LLM client not ready — set LLM_API_KEY so the VLM can "
                         "locate the tower and grass.")

    screencap("outputs/logs/current.png")
    if not solidly_in_match():
        print("doesn't look like you're solidly in a match — the HUD cash/round "
              "wasn't detected. Make sure the battlefield is on screen, then re-run.")

    cash_before = read_hud().get("cash")
    print(f"cash before = {cash_before}")

    spot = place_one(1, [])   # the real gameplay placement, with all fixes

    screencap("outputs/logs/current.png")
    cash_after = read_hud().get("cash")
    if spot:
        print(f"PLACED at {spot}  (cash {cash_before} -> {cash_after})")
    else:
        print(f"NOT placed  (cash {cash_before} -> {cash_after})")
        print("   Inspect outputs/logs/place1_try*_drag.png and *_taptap.png to see "
              "where it aimed. If the spot was good but nothing dropped, the gesture "
              "hold may need to be longer (drag hold_ms in adb_utils.py).")


if __name__ == "__main__":
    main()
