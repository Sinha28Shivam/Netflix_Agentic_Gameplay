"""
src/games/base.py — GameProfile, the genre-neutral base interface.

A GameProfile is everything the engine needs to know about ONE game. It
deliberately assumes NOTHING about economy, rounds, or placement — those are
tower-defense concepts and live in ``src/games/genres/tower_defense.py``.
A game either mixes in a genre (``class MyTD(TowerDefenseMixin, GameProfile)``)
or subclasses ``GameProfile`` directly for a bespoke genre.

Required of every game: identity (``game_id``/``display_name``/``package``),
a mission, its scene vocabulary, and ``build_requirements()``. Everything else
has a safe default so a minimal game only implements what it actually needs.

Behavior hooks that the engine will (in later phases) call through the active
game — ``read_hud``/``is_defeat``/``on_main_menu`` — default to the engine's
existing generic helpers, so wiring them up changes nothing until a game
overrides them.
"""

from __future__ import annotations

import inspect
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

# The universal scenes every game has. A game extends this with its own.
BASE_SCENES: List[str] = ["loading", "main_menu", "dialog", "victory", "defeat", "unknown"]


@dataclass
class PlayResult:
    """Loose result of an in-match routine — intentionally genre-neutral so a
    tower-defense game, a puzzle, and a runner can all return one."""
    placed: List[Any] = field(default_factory=list)
    rounds: Any = None
    suite_ran: bool = False
    notes: Dict[str, Any] = field(default_factory=dict)


class GameProfile(ABC):
    # ---- identity (subclasses MUST set these) -------------------------------
    game_id: str = ""
    display_name: str = ""
    package: str = ""
    activity: str = ""

    # ---- mission / goal -----------------------------------------------------
    mission_summary: str = ""          # human-readable, e.g. "Reach Round 10"
    goal: Dict[str, Any] = {}          # opaque to the engine

    # ---- scenes / RL --------------------------------------------------------
    scene_vocabulary: List[str] = BASE_SCENES
    rl_goal_scene: str = "main_menu"
    scene_to_state_aliases: Dict[str, str] = {}

    # ---- self-contained data files (default: <pkg>/data/…) ------------------
    @property
    def seed_file(self) -> str:
        return os.path.join(self._pkg_dir(), "data", "map_seed.json")

    @property
    def specs_file(self) -> str:
        return os.path.join(self._pkg_dir(), "data", "specs.json")

    def _pkg_dir(self) -> str:
        """Directory of the concrete subclass — lets a plugin ship its own data."""
        return os.path.dirname(inspect.getfile(self.__class__))

    # ---- behavior hooks (override as needed) --------------------------------
    def element_descriptions(self) -> Dict[str, str]:
        """VLM natural-language element prompts keyed by role, e.g.
        ``{"start_button": "the green play button …"}``. Empty by default."""
        return {}

    @abstractmethod
    def build_requirements(self) -> List[Any]:
        """Return this game's list of RequirementSpec objects."""
        raise NotImplementedError

    def gameplay_check_registry(self) -> Dict[str, Callable]:
        """Game-specific check_fn name -> callable, merged with the engine's
        generic checks by the TestRunner. Empty by default."""
        return {}

    def objective_for_scene(self, scene: str) -> str:
        return "Observe"

    def is_goal_reached(self, state: Dict[str, Any]) -> bool:
        return False

    def is_terminal(self, state: Dict[str, Any]) -> bool:
        return state.get("scene") in ("victory", "defeat")

    def read_hud(self, png: str) -> Dict[str, Any]:
        """Interpret the on-screen HUD. Default delegates to the engine's
        generic reader; a game overrides only if its HUD differs."""
        from src.core import qa_common
        return qa_common._generic_read_hud(png)

    def is_defeat(self, png: str) -> bool:
        """True if a defeat / game-over screen is showing. Default = a plain
        OCR match for the words, using the engine's existing text finder."""
        from src.core import qa_common
        return bool(
            qa_common.find_text(png, "defeat") or qa_common.find_text(png, "game over")
        )

    def on_main_menu(self, png: str) -> bool:
        from src.core import qa_common
        return qa_common._generic_on_main_menu(png)

    def play(self, ctx: Any = None, *args: Any, **kwargs: Any) -> PlayResult:
        """In-match action routine. Default is a no-op (navigation-only games)."""
        return PlayResult()

    def run_in_match_suite(self, q: Any, *args: Any, **kwargs: Any) -> Any:
        """In-match interaction test suite. No-op by default."""
        return None
