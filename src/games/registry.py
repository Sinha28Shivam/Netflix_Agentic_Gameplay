"""
src/games/registry.py — the game plugin registry.

Mirrors the resolve-once pattern of ``src/device/device.py``: games register
themselves at import time, and callers resolve the active game by id. This is
the single seam that replaces the scattered ``bloons_td6`` defaults and the
former one-entry ``requirement_sets`` dict in ``scripts/map_and_plan.py``.

Usage:
    from src.games.registry import register, get_game, available_games

    @register
    class MyGame(GameProfile):
        game_id = "my_game"
        ...

    game = get_game("my_game")          # -> MyGame() instance
    ids  = available_games()            # -> ["bloons_td6", "my_game", ...]
"""

from typing import Dict, List, Type

# game_id -> GameProfile subclass. Populated by @register at import time.
_REGISTRY: Dict[str, type] = {}


def register(cls: type) -> type:
    """Class decorator: register a GameProfile subclass under its ``game_id``."""
    game_id = getattr(cls, "game_id", "") or ""
    if not game_id:
        raise ValueError(
            f"{cls.__name__} must define a non-empty class attribute 'game_id' to register."
        )
    if game_id in _REGISTRY and _REGISTRY[game_id] is not cls:
        raise ValueError(
            f"game_id '{game_id}' is already registered to {_REGISTRY[game_id].__name__}; "
            f"{cls.__name__} tried to claim the same id."
        )
    _REGISTRY[game_id] = cls
    return cls


def _ensure_loaded() -> None:
    """Trigger sub-package discovery so the registry is fully populated."""
    from src.games import discover
    discover()


def get_game(game_id: str):
    """Return a fresh instance of the game registered under ``game_id``."""
    _ensure_loaded()
    if game_id not in _REGISTRY:
        raise KeyError(
            f"No game registered for id '{game_id}'. "
            f"Available games: {available_games()}"
        )
    return _REGISTRY[game_id]()


def available_games() -> List[str]:
    """Sorted list of all registered game ids."""
    _ensure_loaded()
    return sorted(_REGISTRY)
