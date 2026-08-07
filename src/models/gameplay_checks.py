"""
gameplay_checks.py — deterministic check_fn implementations referenced by
RequirementSpec.check_fn in category_specs.py.

This is the missing link between PlannerAgent's output (a TestCase with a
check_fn STRING like "assert_cash_updates_after_sell_and_replace") and an
actual pass/fail verdict. Every function here:
  - takes the final `state` dict (same shape VisionAgent.observe returns,
    plus whatever the device/perf layers attach) and the TestCase's
    check_args
  - returns a dict: {"status": "PASS"|"FAIL", "reason": str}
  - is a plain rule over state fields — no model call — matching the
    same "exact assertions" principle compliance_oracle.py applies to
    compliance checks

Checks marked requires_ai_judge=True in category_specs.py (e.g. the
red/white/green placement-validity read) are NOT implemented here as
rules — TestRunner routes those to VerificationJudge instead, the same
confidence-gated path compliance checks use. See TestRunner.run() in
test_runner.py for the routing logic.

This file will grow per-game, same as category_specs.py — that's
expected and is the "extensibility" tradeoff: check logic is config/code
that scales with games, not with test count, since most checks share
patterns (currency present, modal dismissed, state field in range).
"""

from typing import Any, Dict


def assert_screen_reached_with_currency_visible(state: Dict, check_args: Dict) -> Dict[str, Any]:
    required_fields = check_args.get("required_fields", ["cash"])
    resources = state.get("resources", {}) or {}
    missing = [f for f in required_fields if resources.get(f) is None]
    return (
        {"status": "PASS", "reason": f"Screen reached with {required_fields} visible"}
        if not missing
        else {"status": "FAIL", "reason": f"Missing required currency field(s): {missing}"}
    )


def assert_targeting_cycles_through_all_states(state: Dict, check_args: Dict) -> Dict[str, Any]:
    expected_states = check_args.get("expected_states", [])
    observed = state.get("targeting_states_seen", [])
    missing = [s for s in expected_states if s not in observed]
    return (
        {"status": "PASS", "reason": "All targeting states observed"}
        if not missing
        else {"status": "FAIL", "reason": f"Targeting states never observed: {missing}"}
    )


def assert_third_path_locks_after_threshold(state: Dict, check_args: Dict) -> Dict[str, Any]:
    locked_path_index = check_args.get("locked_path_index", 3)
    locked_paths = state.get("locked_upgrade_paths", [])
    return (
        {"status": "PASS", "reason": f"Path {locked_path_index} correctly shows locked"}
        if locked_path_index in locked_paths
        else {"status": "FAIL", "reason": f"Path {locked_path_index} did not lock as expected"}
    )


def assert_game_speed_multiplier_applied(state: Dict, check_args: Dict) -> Dict[str, Any]:
    expected = check_args.get("expected_multiplier", 3)
    observed = state.get("game_speed_multiplier")
    return (
        {"status": "PASS", "reason": f"Speed multiplier is {observed}x"}
        if observed == expected
        else {"status": "FAIL", "reason": f"Expected {expected}x speed, observed {observed}"}
    )


def assert_ability_cooldown_overlay_shown_after_use(state: Dict, check_args: Dict) -> Dict[str, Any]:
    slot = check_args.get("ability_slot", "hero")
    cooldowns = state.get("ability_cooldowns", {}) or {}
    on_cooldown = cooldowns.get(slot, False)
    return (
        {"status": "PASS", "reason": f"{slot} ability shows cooldown after use"}
        if on_cooldown
        else {"status": "FAIL", "reason": f"{slot} ability cooldown overlay not detected after use"}
    )


def assert_cash_updates_after_sell_and_replace(state: Dict, check_args: Dict) -> Dict[str, Any]:
    cash_before = state.get("cash_before_resell")
    cash_after = state.get("resources", {}).get("cash")
    tower_replaced = state.get("tower_replaced_same_footprint", False)
    if cash_before is None or cash_after is None:
        return {"status": "FAIL", "reason": "Could not read cash before/after resell"}
    if cash_after == cash_before:
        return {"status": "FAIL", "reason": "Cash did not change after sell+replace sequence"}
    if check_args.get("same_footprint") and not tower_replaced:
        return {"status": "FAIL", "reason": "Replacement tower not placed in same footprint"}
    return {"status": "PASS", "reason": "Cash updated and tower replaced in same footprint"}


def assert_restart_reloads_map_with_full_health(state: Dict, check_args: Dict) -> Dict[str, Any]:
    scene = state.get("scene")
    base_health = (state.get("resources", {}) or {}).get("base_health")
    max_health = (state.get("resources", {}) or {}).get("base_health_max")
    if scene == "defeat":
        return {"status": "FAIL", "reason": "Still on defeat screen, restart did not trigger"}
    if base_health is None or max_health is None:
        return {"status": "FAIL", "reason": "Could not read base health after restart"}
    return (
        {"status": "PASS", "reason": "Map reloaded with full base health"}
        if base_health >= max_health
        else {"status": "FAIL", "reason": f"Base health {base_health}/{max_health} after restart, expected full"}
    )


def assert_overlay_dismissed_and_run_resumes(state: Dict, check_args: Dict) -> Dict[str, Any]:
    scene = state.get("scene")
    blocking_modal = state.get("blocking_modal")
    if scene == "system_update_modal" or blocking_modal:
        return {"status": "FAIL", "reason": "Overlay still blocking after dismiss attempt"}
    return {"status": "PASS", "reason": "Overlay dismissed, run resumed"}


def assert_fps_above_threshold(state: Dict, check_args: Dict) -> Dict[str, Any]:
    min_fps = check_args.get("min_fps", 30)
    observed = state.get("performance", {}).get("avg_fps")
    if observed is None:
        return {"status": "FAIL", "reason": "No FPS sample captured during check window"}
    return (
        {"status": "PASS", "reason": f"Average FPS {observed} >= {min_fps}"}
        if observed >= min_fps
        else {"status": "FAIL", "reason": f"Average FPS {observed} below {min_fps} floor"}
    )


# check_fn name -> implementation. TestRunner looks up by this name.
GAMEPLAY_CHECK_REGISTRY = {
    "assert_screen_reached_with_currency_visible": assert_screen_reached_with_currency_visible,
    "assert_targeting_cycles_through_all_states": assert_targeting_cycles_through_all_states,
    "assert_third_path_locks_after_threshold": assert_third_path_locks_after_threshold,
    "assert_game_speed_multiplier_applied": assert_game_speed_multiplier_applied,
    "assert_ability_cooldown_overlay_shown_after_use": assert_ability_cooldown_overlay_shown_after_use,
    "assert_cash_updates_after_sell_and_replace": assert_cash_updates_after_sell_and_replace,
    "assert_restart_reloads_map_with_full_health": assert_restart_reloads_map_with_full_health,
    "assert_overlay_dismissed_and_run_resumes": assert_overlay_dismissed_and_run_resumes,
    "assert_fps_above_threshold": assert_fps_above_threshold,
}
