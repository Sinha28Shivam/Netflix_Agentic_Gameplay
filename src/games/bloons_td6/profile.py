"""
src/games/bloons_td6/profile.py — Bloons TD 6, the reference implementation.

PHASE 1: this profile is a thin façade that RE-EXPORTS the existing Bloons
modules (config constants, requirement specs, element descriptions, checks,
scenarios). Behavior is therefore byte-identical to before the registry existed
— the golden/characterization tests guard that. Later phases physically move
those modules into this package; callers won't notice because they already go
through this profile.
"""

import src.core.config as config
from src.games.base import GameProfile
from src.games.genres.tower_defense import TowerDefenseMixin
from src.games.registry import register

# The full Bloons scene vocabulary: the VisionAgent enum plus the extra screens
# category_specs.py references (tower_detail / system_update_modal).
_BLOONS_SCENES = [
    "loading", "main_menu", "map_selection", "difficulty_selection", "game_mode",
    "placement", "in_round", "between_rounds", "victory", "defeat", "dialog",
    "tower_detail", "system_update_modal", "unknown",
]


@register
class BloonsTD6(TowerDefenseMixin, GameProfile):
    game_id = "bloons_td6"
    display_name = "Bloons TD 6"

    # Identity re-exported from config so overrides via env still apply.
    package = config.GAME_PACKAGE
    activity = config.GAME_ACTIVITY

    mission_summary = "Reach Round 10 on Monkey Meadow"
    goal = dict(config.MISSION)

    scene_vocabulary = _BLOONS_SCENES
    rl_goal_scene = config.RL_GOAL_SCENE

    @property
    def scene_to_state_aliases(self):
        from src.rl.rl_decision_agent import SCENE_TO_STATE_ALIASES
        return dict(SCENE_TO_STATE_ALIASES)

    # Bloons keeps its seed/specs at the historical repo paths (config) rather
    # than the package-local default. Physical relocation is deferred; this keeps
    # GAME.seed_file/specs_file accurate meanwhile.
    @property
    def seed_file(self):
        return config.SEED_FILE

    @property
    def specs_file(self):
        return config.SPECS_FILE

    # ---- behavior hooks: re-export today's Bloons modules -------------------
    def build_requirements(self):
        from src.games.bloons_td6.specs import BLOONS_REQUIREMENTS
        return BLOONS_REQUIREMENTS

    def element_descriptions(self):
        from src.games.bloons_td6 import descriptions as d
        return {
            "dart": d.DART_DESC,
            "bomb": d.BOMB_DESC,
            "ice": d.ICE_DESC,
            "tack": d.TACK_DESC,
            "grass": d.GRASS_DESC,
            "grass_fallback": d.GRASS_FALLBACK,
            "start_round": d.GREEN_DESC,
            "fast_forward": d.FF_DESC,
            "back": d.BACK_DESC,
            "confirm_play": d.CONFIRM_PLAY_DESC,
        }

    def gameplay_check_registry(self):
        from src.models.gameplay_checks import GAMEPLAY_CHECK_REGISTRY
        return dict(GAMEPLAY_CHECK_REGISTRY)

    def objective_for_scene(self, scene):
        # Mirrors src/models/objectives.py's map, sourced from this game's goal.
        objectives = {
            "loading": "Wait for load",
            "main_menu": "Open Play menu",
            "map_selection": f"Select {self.goal['map']}",
            "difficulty_selection": f"Select {self.goal['difficulty']}",
            "game_mode": f"Select {self.goal['mode']}",
            "placement": "Place starting tower",
            "between_rounds": "Start next round",
            "in_round": "Monitor round",
            "victory": "Verify victory screen",
            "defeat": "Verify defeat screen",
            "dialog": "Dismiss dialog",
        }
        return objectives.get(scene, "Observe")

    def is_goal_reached(self, state):
        rnd = (state.get("resources", {}) or {}).get("round")
        return rnd is not None and rnd >= self.goal.get("target_round", 10)

    def on_main_menu(self, png):
        # Bloons-specific home/rules-card/mode-select vocabulary (unchanged from
        # the original qa_common._on_main_menu heuristic).
        from src.core.qa_common import clean_tokens, ocr_all
        blob = " ".join(t.lower() for t in clean_tokens(ocr_all(png), cap=40))
        return any(w in blob for w in (
            "heroes", "legends", "knowledge", "play social",
            "change hero", "monkeys cost", "bloons move", "medal",
            "beginner", "intermediate", "advanced", "expert",
            "rewards", "continue saved game",
        ))

    def run_in_match_suite(self, q, placed_pts=None, dart_desc=None):
        from src.games.bloons_td6 import scenarios
        if dart_desc is None:
            dart_desc = self.element_descriptions()["dart"]
        return scenarios.run_in_match_suite(q, placed_pts or [], dart_desc)

    def play(self, ctx=None):
        # Delegate to the existing (unchanged) tower-defense loop so behavior is
        # byte-identical; wrap its tuple into the genre-neutral PlayResult.
        from src.agents.execution.executor_agent import play as _td_play
        from src.games.base import PlayResult
        target = int(self.goal.get("target_round", 10))
        placed, rounds, suite = _td_play(target_round=target)
        return PlayResult(placed=list(range(placed)), rounds=rounds,
                          suite_ran=bool(suite), notes={"suite": suite})
