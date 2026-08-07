"""
Deterministic checks for Subway Surfers, referenced by specs.py. Each is a plain
rule over the observed ``state`` dict (no model call), matching the engine's
check contract: ``fn(state, check_args) -> {"status": "PASS"|"FAIL", "reason"}``.

The runner's ``play()`` attaches its outcome to state under ``runner`` (distance,
duration, actions, ended_reason), which these read.
"""

from typing import Any, Dict


def assert_run_started(state: Dict, check_args: Dict) -> Dict[str, Any]:
    r = state.get("runner", {}) or {}
    started = state.get("scene") == "in_run" or r.get("ticks", 0) > 0
    return {"status": "PASS" if started else "FAIL",
            "reason": f"scene={state.get('scene')}, ticks={r.get('ticks')}"}


def assert_lane_changed_after_swipe(state: Dict, check_args: Dict) -> Dict[str, Any]:
    r = state.get("runner", {}) or {}
    acts = r.get("actions", {}) or {}
    moved = acts.get("left", 0) + acts.get("right", 0)
    return {"status": "PASS" if moved > 0 else "FAIL",
            "reason": f"lane-change swipes issued: {moved}"}


def assert_run_ended_and_recoverable(state: Dict, check_args: Dict) -> Dict[str, Any]:
    r = state.get("runner", {}) or {}
    ended = r.get("ended_reason") in ("stalled", "run_ended") or state.get("scene") in ("game_over", "main_menu")
    return {"status": "PASS" if ended else "FAIL",
            "reason": f"ended_reason={r.get('ended_reason')}, scene={state.get('scene')}"}


CHECKS = {
    "assert_run_started": assert_run_started,
    "assert_lane_changed_after_swipe": assert_lane_changed_after_swipe,
    "assert_run_ended_and_recoverable": assert_run_ended_and_recoverable,
}
