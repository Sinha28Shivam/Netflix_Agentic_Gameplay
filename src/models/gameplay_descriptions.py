"""
Compatibility shim. The Bloons element descriptions now live in the game plugin
at ``src/games/bloons_td6/descriptions.py`` (a game owns its own logic). This
re-export keeps existing imports working; prefer importing from the plugin, or
via ``active_game.GAME.element_descriptions()``.
"""

from src.games.bloons_td6.descriptions import *  # noqa: F401,F403
