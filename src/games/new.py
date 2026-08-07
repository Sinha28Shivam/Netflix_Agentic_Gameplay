"""
Scaffold a new game plugin from the template.

    python -m src.games.new <game_id> [--genre raw|tower_defense]
                                      [--package com.x.y] [--name "Display Name"]

Copies src/games/_template/ to src/games/<game_id>/, fills the placeholders, and
(for --genre tower_defense) wires in the TowerDefenseMixin. You then edit only
files inside your new folder. Nothing in the engine changes.
"""

import argparse
import os
import re
import shutil

_HERE = os.path.dirname(__file__)
_TEMPLATE = os.path.join(_HERE, "_template")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _class_name(game_id: str) -> str:
    parts = [p for p in re.split(r"[_\-\s]+", game_id) if p]
    return "".join(p.capitalize() for p in parts) or "Game"


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold a new game plugin")
    ap.add_argument("game_id", help="lowercase id, e.g. my_game (also the folder name)")
    ap.add_argument("--genre", choices=["raw", "tower_defense"], default="raw")
    ap.add_argument("--package", default=None, help="Android package name")
    ap.add_argument("--name", default=None, help="Human display name")
    args = ap.parse_args()

    if not _ID_RE.match(args.game_id):
        raise SystemExit(f"Invalid game_id '{args.game_id}': use lowercase letters, digits, underscores.")

    dest = os.path.join(_HERE, args.game_id)
    if os.path.exists(dest):
        raise SystemExit(f"src/games/{args.game_id}/ already exists — pick another id.")

    class_name = _class_name(args.game_id)
    display = args.name or args.game_id.replace("_", " ").title()
    package = args.package or f"com.example.{args.game_id}"
    repl = {
        "__GAME_ID__": args.game_id,
        "__CLASS_NAME__": class_name,
        "__DISPLAY_NAME__": display,
        "__PACKAGE__": package,
    }

    shutil.copytree(_TEMPLATE, dest)

    for root, _dirs, files in os.walk(dest):
        for fname in files:
            if not fname.endswith((".py", ".json", ".md")):
                continue
            path = os.path.join(root, fname)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for token, value in repl.items():
                text = text.replace(token, value)
            if args.genre == "tower_defense" and fname == "profile.py":
                text = text.replace(
                    "from src.games.base import GameProfile",
                    "from src.games.base import GameProfile\n"
                    "from src.games.genres.tower_defense import TowerDefenseMixin",
                )
                text = text.replace(
                    f"class {class_name}(GameProfile):",
                    f"class {class_name}(TowerDefenseMixin, GameProfile):",
                )
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    print(f"Created src/games/{args.game_id}/ (class {class_name}, genre={args.genre}).")
    print("Next:")
    print(f"  1. Edit src/games/{args.game_id}/profile.py (scenes, package, hooks)")
    print(f"  2. python -m src.games.validate {args.game_id}")
    print(f"  3. python main.py --game {args.game_id} --map")


if __name__ == "__main__":
    main()
