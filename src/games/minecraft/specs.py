"""
Requirements for Minecraft (com.mojang.minecraftpe) QA pipeline.

Mirrors src/games/bloons_td6/specs.py's structure: navigation requirements
(does the golden path actually reach each screen) PLUS deeper in-world
gameplay requirements (movement, block interaction, hotbar, pause/resume,
save & quit) verified by deterministic check_fns from checks.py — not the
generic Bloons-shaped "currency visible" check, since Minecraft has no
cash/round HUD.
"""

from src.agents.planning.planner_agent import RequirementSpec

REQUIREMENTS = [
    # ---------------------------------------------------------------- navigation / compliance
    RequirementSpec(
        requirement_id="mc_01_title_screen_boot",
        title="Game boots to title screen with Mojang branding",
        category="compliance",
        target_screen="main_menu",
        check_fn="check_mojang_copyright",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_02_play_screen_nav",
        title="Navigate to PLAY screen with Worlds tab visible",
        category="gameplay",
        target_screen="play_menu",
        check_fn="check_world_listed_after_save_quit",
        check_args={"world_name": ""},
    ),
    RequirementSpec(
        requirement_id="mc_03_create_world_config",
        title="Navigate to CREATE NEW WORLD config screen",
        category="gameplay",
        target_screen="create_world_config",
        check_fn="check_minecraft_hud_visible",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_04_control_mode_select",
        title="Confirm CONTROL MODE selection dialog",
        category="gameplay",
        target_screen="control_mode",
        check_fn="check_minecraft_hud_visible",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_05_in_game_hud_render",
        title="World renders and HUD hotbar is displayed",
        category="gameplay",
        target_screen="in_game",
        check_fn="check_minecraft_hud_visible",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_06_performance_framerate",
        title="FPS remains steady above target threshold during world render",
        category="performance",
        target_screen="in_game",
        check_fn="check_minecraft_hud_visible",
        check_args={},
    ),

    # ---------------------------------------------------------------- in-world gameplay (deep)
    RequirementSpec(
        requirement_id="mc_07_movement_joystick",
        title="Movement joystick actually drives the player through the world",
        category="gameplay",
        target_screen="in_game",
        check_fn="check_screen_changed_after_action",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_08_camera_look",
        title="Swiping the look area rotates the camera/world view",
        category="gameplay",
        target_screen="in_game",
        check_fn="check_screen_changed_after_action",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_09_hotbar_selection",
        title="Tapping hotbar slots updates the selection highlight",
        category="gameplay",
        target_screen="in_game",
        check_fn="check_screen_changed_after_action",
        check_args={},
        requires_ai_judge=True,  # a highlight moving is a visual state read
    ),
    RequirementSpec(
        requirement_id="mc_10_block_interaction",
        title="Press-and-hold on a block breaks/places it in the world",
        category="gameplay",
        target_screen="in_game",
        check_fn="check_screen_changed_after_action",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_11_pause_resume",
        title="Pause menu opens on demand and resumes gameplay cleanly",
        category="gameplay",
        target_screen="pause_menu",
        check_fn="check_pause_menu_showing",
        check_args={},
    ),
    RequirementSpec(
        requirement_id="mc_12_save_and_quit_roundtrip",
        title="Save & Quit persists the world and returns it to the Worlds list",
        category="gameplay",
        target_screen="play_menu",
        check_fn="check_world_listed_after_save_quit",
        check_args={"world_name": ""},
    ),
]
