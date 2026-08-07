"""
src/core/active_game.py — resolves THE active game once, from config.

Mirrors ``src/device/device.py``: just as that module binds the chosen device
backend at import time from ``EXECUTION_MODE``, this binds the chosen game from
``config.GAME_ID``. Engine code that needs per-game behavior imports ``GAME``
from here and calls its methods, instead of importing Bloons constants directly.

    from src.core.active_game import GAME
    pkg = GAME.package

To switch games, set GAME_ID / pass --game BEFORE this module is first imported
(entry points do this), exactly like EXECUTION_MODE.
"""

import src.core.config as config
from src.games.registry import get_game

GAME = get_game(config.GAME_ID)


def active_package() -> str:
    """Package name of the active game — the device layer's launch/stop target.
    Falls back to config.GAME_PACKAGE if the game didn't declare one."""
    return GAME.package or config.GAME_PACKAGE

