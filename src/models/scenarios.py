"""
Compatibility shim. The Bloons in-match test scenarios now live in the game
plugin at ``src/games/bloons_td6/scenarios.py``. Prefer
``active_game.GAME.run_in_match_suite(...)`` or importing from the plugin.
"""

from src.games.bloons_td6.scenarios import *  # noqa: F401,F403
