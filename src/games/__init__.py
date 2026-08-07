"""
src/games — the pluggable game layer.

Each game lives in its own self-contained sub-package (``src/games/<game_id>/``)
exposing a ``profile.py`` whose GameProfile subclass is decorated with
``@register`` (see ``src/games/registry.py``). Adding a game is therefore
"drop in a folder" — this package auto-discovers every sub-package on import,
so there is no central list to edit.

Discovery deliberately imports only ``<pkg>.profile`` for real game packages
and skips helper modules (``base``, ``registry``), the genre mix-ins package
(``genres``), the copy-me starter (``_template``), and the scaffolding tools
(``new``, ``validate``). Games self-register as a side effect of that import.
"""

import importlib
import os
import pkgutil

_DISCOVERED = False

# Sub-packages / modules that are NOT games and must not be imported as one.
_NON_GAME = {"base", "registry", "genres", "new", "validate"}


def discover() -> None:
    """Import every game sub-package's ``profile`` module exactly once so its
    ``@register`` decorator runs. Idempotent and safe to call repeatedly."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True

    pkg_dir = os.path.dirname(__file__)
    for mod in pkgutil.iter_modules([pkg_dir]):
        name = mod.name
        if not mod.ispkg or name.startswith("_") or name in _NON_GAME:
            continue
        importlib.import_module(f"{__name__}.{name}.profile")
