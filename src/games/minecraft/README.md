# Game plugin template

This folder is a **copy-me starting point** for adding a new game. The leading
underscore keeps it out of auto-discovery, so it never registers as a real game.

## Fastest way to use it

```bash
python -m src.games.new my_game --genre raw       # or: tower_defense
```

That copies this folder to `src/games/my_game/`, fills in the placeholders
(`minecraft`, `Minecraft`, `Minecraft`, `com.example.minecraft`), and wires
the genre mix-in if you asked for one. Then:

```bash
python -m src.games.validate my_game              # device-free sanity check
python main.py --game my_game --map               # build the screen map on a device
```

## What each file is for

| File | What you put in it |
|------|--------------------|
| `profile.py` | The one class the engine reads: identity, scenes, and behavior hooks. Start here. |
| `descriptions.py` | `ELEMENTS`: natural-language prompts the VLM uses to find on-screen elements (no coordinates). |
| `specs.py` | `REQUIREMENTS`: the list of things to test; each `target_screen` must be in your `scene_vocabulary`. |
| `checks.py` | `CHECKS`: deterministic pass/fail rules referenced by your specs. Engine-generic checks are merged in automatically. |
| `data/map_seed.json` | The navigation "golden path" (button labels) from the main menu into a match. |
| `data/specs.json` | Optional free-text requirements the planner can expand. |

## The rules that matter

1. You should only ever edit files **inside your own `src/games/<id>/` folder**.
   No engine edits are needed to add a game.
2. Every `target_screen` in `specs.py` must appear in `profile.scene_vocabulary`
   — `validate` fails loudly if not (this is the #1 mistake).
3. Locate elements by **describing them**, never by pixel coordinates.
4. Override `read_hud` / `is_defeat` / `on_main_menu` / `play` only if your game
   differs from the engine defaults — otherwise leave them alone.

See `docs/ADDING_A_GAME.md` for the full walkthrough, with Bloons TD6
(`src/games/bloons_td6/`) as the worked reference implementation.
