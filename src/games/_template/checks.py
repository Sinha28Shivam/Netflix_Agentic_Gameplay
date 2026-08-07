"""
Deterministic checks for __DISPLAY_NAME__.

A check is ``fn(state: dict, check_args: dict) -> {"status": "PASS"|"FAIL",
"reason": str}`` — a plain rule over the observed state, no model call. Register
each under the name your specs reference. Engine-generic checks (e.g.
``assert_screen_reached_with_currency_visible``) are always available and merged
in automatically, so you only add game-specific ones here.
"""

from typing import Any, Dict


def assert_example(state: Dict, check_args: Dict) -> Dict[str, Any]:
    ok = state.get("scene") == check_args.get("expected_scene")
    return {"status": "PASS" if ok else "FAIL",
            "reason": f"scene={state.get('scene')}"}


# check_fn name -> callable. Referenced by RequirementSpec.check_fn in specs.py.
CHECKS = {
    "assert_example": assert_example,
}
