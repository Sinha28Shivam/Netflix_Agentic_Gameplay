"""
src/games/subway_surfers/profile.py — Subway Surfers, the endless-runner
reference plugin.

Menu navigation (boot -> start a run, handle game-over) reuses the engine's
existing VLM/OCR path. The RUN itself is driven by the real-time stack:
  fast_io (scrcpy/adb) -> perception.perceive (cv2) -> RunnerMixin.decide -> swipe.

Requires the fast-I/O + CV tooling (see this folder's README): OpenCV, and
ideally scrcpy + scrcpy-client for real-time capture/input. The adb fallback
runs but is too slow to survive long.
"""

import json
import os
import time

from src.agents.planning.planner_agent import RequirementSpec  # noqa: F401 (used via specs)
from src.games.base import GameProfile, PlayResult
from src.games.genres.runner import RunnerMixin
from src.games.registry import register

_CAL_PATH = os.path.join(os.path.dirname(__file__), "data", "calibration.json")


@register
class SubwaySurfers(RunnerMixin, GameProfile):
    game_id = "subway_surfers"
    display_name = "Subway Surfers"
    package = "com.kiloo.subwaysurf"

    mission_summary = "Survive the run — dodge, switch lanes, jump and roll, grab coins"
    goal = {"target_distance": 2000}

    scene_vocabulary = [
        "loading", "main_menu", "in_run", "pause", "revive",
        "results", "game_over", "shop", "dialog", "unknown",
    ]

    # Runner loop tuning (overrides RunnerMixin defaults).
    tick_hz = 15
    max_run_seconds = 180

    # ---- requirements / descriptions / checks ------------------------------
    def build_requirements(self):
        from src.games.subway_surfers.specs import REQUIREMENTS
        return REQUIREMENTS

    def element_descriptions(self):
        from src.games.subway_surfers.descriptions import ELEMENTS
        return ELEMENTS

    def gameplay_check_registry(self):
        from src.games.subway_surfers.checks import CHECKS
        return dict(CHECKS)

    def objective_for_scene(self, scene):
        return {
            "loading": "Wait for load",
            "main_menu": "Tap to start a run",
            "in_run": "Survive: dodge, switch lanes, jump, roll",
            "pause": "Resume the run",
            "revive": "Decline revive / continue",
            "game_over": "Return to the main menu",
            "results": "Acknowledge results",
            "shop": "Browse the shop",
            "dialog": "Dismiss dialog",
        }.get(scene, "Observe")

    def is_goal_reached(self, state):
        r = (state.get("runner") or {})
        return (r.get("distance") or 0) >= self.goal.get("target_distance", 2000)

    # ---- perception (CV) ---------------------------------------------------
    def _calibration(self):
        try:
            with open(_CAL_PATH, encoding="utf-8") as fh:
                return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
        except Exception:
            return None

    def perceive(self, frame):
        from src.games.subway_surfers.perception import perceive
        return perceive(frame, self._calibration())

    # ---- HUD: score / coins (top strip). OCR-based, end-of-run only --------
    def read_hud(self, png):
        from src.core.qa_common import ocr_all
        out = {"score": None, "coins": None}
        try:
            from PIL import Image
            w, h = Image.open(png).size
        except Exception:
            w = h = None
        nums = []
        for it in ocr_all(png):
            t = it["text"].replace(",", "").strip()
            if t.isdigit():
                nums.append((it["x"], it["y"], int(t)))
        if not nums:
            return out
        # score = largest number in the top strip; coins = a top-right number
        top = [n for n in nums if (h is None or n[1] < h * 0.15)]
        if top:
            out["score"] = max(n[2] for n in top)
            if w is not None:
                right = [n for n in top if n[0] > w * 0.55]
                if right:
                    out["coins"] = min(n[2] for n in right)
        return out

    # ---- the run ------------------------------------------------------------
    def play(self, ctx=None):
        """Start a run (best-effort) and drive it in real time until it ends."""
        from src.device.fast_io import get_fast_io

        source, control = get_fast_io()
        source.start()
        try:
            self._start_run(source, control)
            stats = self.run_until_crash(source, control, max_seconds=self.max_run_seconds)
        finally:
            source.stop()

        return PlayResult(
            rounds=None,
            suite_ran=False,
            notes={
                "duration": stats.get("duration"),
                "ticks": stats.get("ticks"),
                "actions": stats.get("actions"),
                "ended_reason": stats.get("ended_reason"),
            },
        )

    def _start_run(self, source, control):
        """Best-effort: tap the play / tap-to-start prompt to begin a run.
        Falls back to a center tap. Menu detection uses the existing VLM path."""
        png = "outputs/logs/current.png"
        try:
            from src.core import qa_common
            qa_common.screencap(png)
            pt = (qa_common.vlm_locate(png, self.element_descriptions()["tap_to_start"])
                  or qa_common.vlm_locate(png, self.element_descriptions()["play_button"]))
        except Exception:
            pt = None
        frame = source.read()
        if frame is not None:
            h, w = frame.shape[:2]
            control.tap(*(pt if pt else (w // 2, int(h * 0.6))))
        time.sleep(1.5)  # let the run spin up before the control loop starts
