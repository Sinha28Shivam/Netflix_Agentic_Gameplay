"""
Structured requirements for Bloons TD 6, derived 1:1 from Bloons.md.

Each Test N in Bloons.md becomes one RequirementSpec here. `target_screen`
values match the screen_id vocabulary the existing VisionAgent already
emits in agents/vision_agent.py's schema (scene field) — extended with a
few Bloons-specific screens the prototype's prompt doesn't currently name
(tower_detail, defeat, system_update_modal). Extending the vision schema
for a new game is exactly the "setup, not new code" the deck claims —
see the note at the bottom of this file for the one line that needs adding.

check_fn names are deliberately deterministic-sounding (assert_*) — they
are exact rule checks against instrumented state, not VLM opinion. Where
a check genuinely cannot be reduced to a rule (Test 2's "grayed-out to
active" color-state read, Test 3's "red vs white/green" placement
indicator), requires_ai_judge=True is set explicitly, matching the
deck's "AI judge only for ambiguous cases" rule rather than defaulting
everything to AI.
"""

from src.agents.planning.planner_agent import RequirementSpec

BLOONS_REQUIREMENTS = [
    RequirementSpec(
        requirement_id="test_01_title_navigation",
        title="Title Screen Navigation & Profile Handshake",
        category="gameplay",
        target_screen="main_menu",
        check_fn="assert_screen_reached_with_currency_visible",
        check_args={"required_fields": ["cash"]},
    ),
    RequirementSpec(
        requirement_id="test_02_sidebar_carousel",
        title="Sidebar Carousel Navigation",
        category="gameplay",
        target_screen="placement",
        check_fn="assert_tower_panel_scroll_reveals_items",
        check_args={"min_new_items_after_scroll": 1},
        requires_ai_judge=True,  # "grayed-out to active" is a visual state read
    ),
    RequirementSpec(
        requirement_id="test_03_drag_drop_placement",
        title="Drag-and-Drop Placement Validation",
        category="gameplay",
        target_screen="placement",
        check_fn="assert_tower_snapped_to_legal_tile",
        check_args={"illegal_tile_types": ["path", "rock", "occupied"]},
        requires_ai_judge=True,  # red/white/green validity color is a visual read
    ),
    RequirementSpec(
        requirement_id="test_04_target_priority",
        title="Target Priority Adjustment",
        category="gameplay",
        target_screen="tower_detail",
        check_fn="assert_targeting_cycles_through_all_states",
        check_args={"expected_states": ["First", "Last", "Close", "Strong"]},
    ),
    RequirementSpec(
        requirement_id="test_05_upgrade_path_lock",
        title="Upgrade Path Branching Logic",
        category="gameplay",
        target_screen="tower_detail",
        check_fn="assert_third_path_locks_after_threshold",
        check_args={"locked_path_index": 3, "threshold_tier": 2},
    ),
    RequirementSpec(
        requirement_id="test_06_battle_speed_toggle",
        title="Battle Speed Toggle",
        category="gameplay",
        target_screen="in_round",
        check_fn="assert_game_speed_multiplier_applied",
        check_args={"expected_multiplier": 3},
    ),
    RequirementSpec(
        requirement_id="test_07_cooldown_ability_sync",
        title="Cooldown Ability Synchronization",
        category="gameplay",
        target_screen="in_round",
        check_fn="assert_ability_cooldown_overlay_shown_after_use",
        check_args={"ability_slot": "hero"},
    ),
    RequirementSpec(
        requirement_id="test_08_resell_infrastructure",
        title="Micro-Management Re-Sell Infrastructure",
        category="gameplay",
        target_screen="in_round",
        check_fn="assert_cash_updates_after_sell_and_replace",
        check_args={"same_footprint": True},
    ),
    RequirementSpec(
        requirement_id="test_09_defeat_modal",
        title="Defeat Modal Interaction",
        category="gameplay",
        target_screen="defeat",
        check_fn="assert_restart_reloads_map_with_full_health",
    ),
    RequirementSpec(
        requirement_id="test_10_system_update_overlay",
        title="System Update Notification Handling",
        category="gameplay",
        target_screen="system_update_modal",
        check_fn="assert_overlay_dismissed_and_run_resumes",
        check_args={"max_seconds_to_resume": 10},
    ),
    # --- Compliance checks (separate from Bloons.md's gameplay-only list,
    #     included to show the category the prototype is currently missing
    #     a deterministic layer for — see compliance_oracle.py) ---
    RequirementSpec(
        requirement_id="compliance_01_iap_price_disclosure",
        title="In-app purchase prompts show exact price",
        category="compliance",
        target_screen="main_menu",
        check_fn="assert_iap_modal_shows_price_text",
    ),
    RequirementSpec(
        requirement_id="performance_01_in_round_fps_floor",
        title="In-round FPS stays above floor during a full wave",
        category="performance",
        target_screen="in_round",
        check_fn="assert_fps_above_threshold",
        check_args={"min_fps": 30},
    ),
]

# Extension note: target_screen="tower_detail", "defeat", "system_update_modal"
# need adding to VISION_SYSTEM_PROMPT's scene enum in agents/vision_agent.py.
# That one-line prompt edit, plus this file, is the entire "onboarding cost"
# for adding these 12 Bloons checks — no orchestrator/agent code changes.
