"""
Validate a game plugin WITHOUT a device or an LLM.

    python -m src.games.validate <game_id>

Checks that the plugin loads and registers, exposes the required identity and
hooks, its data files parse, and every requirement targets a declared scene
(the most common mistake). Exit code 0 = OK, 1 = problems found.
"""

import argparse
import json
import os
import sys


def validate(game_id: str) -> int:
    from src.games.registry import available_games, get_game

    errors, warns = [], []

    try:
        game = get_game(game_id)
    except Exception as e:  # noqa: BLE001 — surface any load/registration error
        print(f"FAIL: could not load game '{game_id}': {e}")
        print(f"      registered games: {available_games()}")
        return 1

    for attr in ("game_id", "display_name", "package"):
        if not getattr(game, attr, ""):
            errors.append(f"missing required identity field '{attr}'")

    scenes = list(game.scene_vocabulary or [])
    if not scenes:
        errors.append("scene_vocabulary is empty")

    try:
        reqs = game.build_requirements()
    except Exception as e:  # noqa: BLE001
        errors.append(f"build_requirements() raised: {e}")
        reqs = []
    for r in reqs:
        target = getattr(r, "target_screen", None)
        if target and target not in scenes:
            errors.append(
                f"requirement '{getattr(r, 'requirement_id', '?')}' targets scene "
                f"'{target}' which is not in scene_vocabulary"
            )

    try:
        game.element_descriptions()
    except Exception as e:  # noqa: BLE001
        errors.append(f"element_descriptions() raised: {e}")

    for label in ("seed_file", "specs_file"):
        path = getattr(game, label, "")
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    json.load(fh)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label} '{path}' is not valid JSON: {e}")
        else:
            warns.append(f"{label} not found at '{path}' (ok if you build the map fresh)")

    for w in warns:
        print(f"WARN: {w}")
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1

    print(f"OK: '{game_id}' is a valid plugin — "
          f"{len(reqs)} requirement(s), {len(scenes)} scene(s).")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate a game plugin")
    ap.add_argument("game_id")
    args = ap.parse_args()
    sys.exit(validate(args.game_id))


if __name__ == "__main__":
    main()
