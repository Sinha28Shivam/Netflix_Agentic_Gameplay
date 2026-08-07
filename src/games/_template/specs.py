"""
Requirements for __DISPLAY_NAME__ — what the QA pipeline should verify.

Each RequirementSpec becomes a planned test case. ``target_screen`` MUST be a
value from your profile's ``scene_vocabulary`` (the validator enforces this).
``check_fn`` names a callable in checks.py (or an engine-generic check).
"""

from src.agents.planning.planner_agent import RequirementSpec

REQUIREMENTS = [
    RequirementSpec(
        requirement_id="example_01_reaches_menu",
        title="Game boots to the main menu",
        category="gameplay",
        target_screen="main_menu",
        check_fn="assert_screen_reached_with_currency_visible",  # engine-generic
        check_args={"required_fields": []},
    ),
    # Add your real requirements here.
]
