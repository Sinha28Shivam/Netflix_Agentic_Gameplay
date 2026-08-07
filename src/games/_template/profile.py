"""
__DISPLAY_NAME__ — game plugin profile.

This is the ONE file the engine needs to understand your game. Fill in the
identity, list your scenes, and implement the hooks your game actually uses.
Everything else has a safe default (see src/games/base.py). See the sibling
README.md and docs/ADDING_A_GAME.md for the full guide.

Tip: for a tower-defense game, add the genre mix-in for a ready-made economy /
placement play-loop:

    from src.games.genres.tower_defense import TowerDefenseMixin
    class __CLASS_NAME__(TowerDefenseMixin, GameProfile): ...
"""

from src.games.base import GameProfile
from src.games.registry import register


@register
class __CLASS_NAME__(GameProfile):
    # ---- identity (required) ----
    game_id = "__GAME_ID__"                 # unique; also this folder's name
    display_name = "__DISPLAY_NAME__"
    package = "__PACKAGE__"                  # `adb shell pm list packages` to find it
    activity = ""                           # optional explicit launch activity

    # ---- mission / goal ----
    mission_summary = "Describe the run goal in one line"
    goal = {}                               # opaque to the engine; your hooks read it

    # ---- scenes: every screen your VisionAgent may report ----
    # Base scenes (loading/main_menu/dialog/victory/defeat/unknown) are always
    # valid; add your game's own screens here.
    scene_vocabulary = [
        "loading", "main_menu", "dialog", "victory", "defeat", "unknown",
        # e.g. "level_select", "in_level", "results",
    ]

    # ---- requirements: what to test (see specs.py) ----
    def build_requirements(self):
        from . import specs
        return specs.REQUIREMENTS

    # ---- element descriptions: how the VLM finds things (see descriptions.py) ----
    def element_descriptions(self):
        from . import descriptions
        return descriptions.ELEMENTS

    # ---- deterministic checks referenced by your specs (see checks.py) ----
    def gameplay_check_registry(self):
        from . import checks
        return checks.CHECKS

    # ---- what the agent should try to do on each screen ----
    def objective_for_scene(self, scene):
        return {
            "main_menu": "Open the play menu",
            # "in_level": "Play the level",
        }.get(scene, "Observe")

    # ---- goal / terminal detection ----
    def is_goal_reached(self, state):
        # Return True when your win/goal condition is observed in `state`.
        return state.get("scene") == "victory"

    # ---- OPTIONAL overrides -------------------------------------------------
    # Override ONLY if your game differs from the engine defaults:
    #   def read_hud(self, png): ...        # parse your HUD numbers
    #   def is_defeat(self, png): ...       # detect your game-over screen
    #   def on_main_menu(self, png): ...    # detect your main menu
    #   def play(self, ctx=None): ...       # your in-match action routine
    #   def run_in_match_suite(self, q, *a, **k): ...  # in-match interaction tests
