"""
src/core/game_select.py — early active-game selection for CLI entry points.

The active game is resolved ONCE, at import time, by src/core/active_game.py
(mirroring how EXECUTION_MODE picks a device backend). So a ``--game <id>`` flag
must be turned into ``GAME_ID`` in the environment BEFORE any module that binds
the active game is imported. Entry points call ``select_game_from_argv()`` as
their very first action, before their project imports.
"""

import os
import sys


def select_game_from_argv(argv=None):
    """If ``--game <id>`` / ``--game=<id>`` is present, set GAME_ID in the
    environment so the active-game singleton binds to it. Returns the chosen id
    (or the existing GAME_ID / None)."""
    argv = argv if argv is not None else sys.argv
    for i, arg in enumerate(argv):
        if arg == "--game" and i + 1 < len(argv):
            os.environ["GAME_ID"] = argv[i + 1]
            return argv[i + 1]
        if arg.startswith("--game="):
            value = arg.split("=", 1)[1]
            os.environ["GAME_ID"] = value
            return value
    return os.environ.get("GAME_ID")
