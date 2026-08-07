"""
QA requirements for Subway Surfers. Every ``target_screen`` must be in the
profile's ``scene_vocabulary`` (the validator enforces this).

Because a run is non-deterministic (procedural track), gameplay requirements
assert on OUTCOMES/INVARIANTS (a run started, an input changed lane, a run ended
and returned to menu) rather than a fixed route.
"""

from src.agents.planning.planner_agent import RequirementSpec

REQUIREMENTS = [
    RequirementSpec(
        requirement_id="ss_01_reaches_main_menu",
        title="Boots to the main menu",
        category="gameplay",
        target_screen="main_menu",
        check_fn="assert_screen_reached_with_currency_visible",
        check_args={"required_fields": []},
    ),
    RequirementSpec(
        requirement_id="ss_02_run_starts",
        title="A run starts from the main menu",
        category="gameplay",
        target_screen="in_run",
        check_fn="assert_run_started",
    ),
    RequirementSpec(
        requirement_id="ss_03_lane_switch_responds",
        title="A left/right swipe changes lane during a run",
        category="gameplay",
        target_screen="in_run",
        check_fn="assert_lane_changed_after_swipe",
        requires_ai_judge=True,   # visual lane-change confirmation
    ),
    RequirementSpec(
        requirement_id="ss_04_game_over_returns",
        title="Crash shows game-over and can return to menu",
        category="gameplay",
        target_screen="game_over",
        check_fn="assert_run_ended_and_recoverable",
    ),
    RequirementSpec(
        requirement_id="ss_perf_01_in_run_fps",
        title="In-run FPS stays above the floor",
        category="performance",
        target_screen="in_run",
        check_fn="assert_fps_above_threshold",
        check_args={"min_fps": 30},
    ),
    RequirementSpec(
        requirement_id="ss_comp_01_shop_iap_price",
        title="Shop in-app purchases show a price",
        category="compliance",
        target_screen="shop",
        check_fn="assert_iap_modal_shows_price_text",
    ),
]
