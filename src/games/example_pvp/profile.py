"""
example_pvp — a minimal SECOND reference plugin (a multiplayer game).

Its purpose is to prove the SDK is genuinely genre-agnostic: it shares NONE of
Bloons' tower-defense mechanics, uses MultiplayerMixin, and is fully
self-contained. It validates without a device
(``python -m src.games.validate example_pvp``). Fill in the real package name
and hooks to point it at an actual multiplayer title.
"""

from src.agents.planning.planner_agent import RequirementSpec
from src.games.base import GameProfile
from src.games.genres.pvp import MultiplayerMixin
from src.games.registry import register


@register
class ExamplePvP(MultiplayerMixin, GameProfile):
    game_id = "example_pvp"
    display_name = "Example PvP (reference)"
    package = "com.example.pvp"

    mission_summary = "Play and finish one online match"
    goal = {"finish_match": True}

    scene_vocabulary = [
        "loading", "main_menu", "matchmaking", "in_match",
        "victory", "defeat", "dialog", "unknown",
    ]

    def build_requirements(self):
        return [
            RequirementSpec(
                requirement_id="pvp_01_reaches_menu",
                title="Boots to the main menu",
                category="gameplay",
                target_screen="main_menu",
                check_fn="assert_screen_reached_with_currency_visible",
                check_args={"required_fields": []},
            ),
        ]

    def element_descriptions(self):
        return {
            "play_button": "the button that starts matchmaking or a new online match",
        }

    def objective_for_scene(self, scene):
        return {
            "main_menu": "Start matchmaking",
            "matchmaking": "Wait for an opponent",
            "in_match": "Play the match",
        }.get(scene, "Observe")

    def is_goal_reached(self, state):
        return self.match_ended(state)

    # --- multiplayer hooks ---
    def match_started(self, png):
        from src.core import qa_common
        return bool(qa_common.find_text(png, "vs") or qa_common.find_text(png, "fight"))
