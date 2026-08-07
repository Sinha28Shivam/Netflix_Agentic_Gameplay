"""
Compatibility shim. The Bloons requirement specs now live in the game plugin at
``src/games/bloons_td6/specs.py``. Prefer ``active_game.GAME.build_requirements()``
or importing from the plugin directly.
"""

from src.games.bloons_td6.specs import *  # noqa: F401,F403
from src.games.bloons_td6.specs import BLOONS_REQUIREMENTS  # noqa: F401
