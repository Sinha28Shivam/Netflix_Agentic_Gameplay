# Adding a game

This framework tests **any** game through a small plugin. You add a game by
dropping a self-contained package into `src/games/<game_id>/` and editing only
files inside that folder — **the engine never changes**. Bloons TD6
(`src/games/bloons_td6/`) is the worked reference.

## 1. Scaffold

```bash
python -m src.games.new my_game --genre raw            # generic game
python -m src.games.new my_td  --genre tower_defense   # inherits an economy/placement play-loop
```

This copies the template to `src/games/my_game/` and fills in the names. Files:

- **`profile.py`** — the one class the engine reads. Start here.
- **`descriptions.py`** — `ELEMENTS`: how the VLM finds on-screen things (words, not coordinates).
- **`specs.py`** — `REQUIREMENTS`: what to test.
- **`checks.py`** — `CHECKS`: deterministic pass/fail rules your specs reference.
- **`data/map_seed.json`** — the button path from the menu into a match.
- **`data/specs.json`** — optional free-text requirements.

## 2. Fill in `profile.py`

Required:

| Field | Meaning |
|-------|---------|
| `game_id` | Unique id; equals the folder name. |
| `display_name` | Human name. |
| `package` | Android package. Find it with `adb shell pm list packages`. |
| `scene_vocabulary` | Every screen your VisionAgent can report. Base scenes (`loading`, `main_menu`, `dialog`, `victory`, `defeat`, `unknown`) are always available — add your own (`level_select`, `in_level`, …). |
| `build_requirements()` | Return your `REQUIREMENTS`. |

Optional hooks — override **only if your game differs** from the engine defaults:

- `read_hud(png)` — parse your HUD numbers (score/lives/currency).
- `is_defeat(png)` / `on_main_menu(png)` — detect those screens.
- `is_goal_reached(state)` — your win condition.
- `play(ctx)` — your in-match action routine (tower-defense games get one free from the mixin).
- `run_in_match_suite(q, …)` — in-match interaction tests.

## 3. Pick a genre (optional)

Genres are mix-ins that pre-supply mechanics:

```python
from src.games.genres.tower_defense import TowerDefenseMixin
class MyTD(TowerDefenseMixin, GameProfile): ...   # economy loop, unit placement
```

Multiplayer games add `MultiplayerMixin` (matchmaking wait, opponent/match-end
detection, outcome-based assertions). Mix-ins compose:
`class Foo(TowerDefenseMixin, MultiplayerMixin, GameProfile)`.

## 4. Validate (no device needed)

```bash
python -m src.games.validate my_game
```

This confirms the plugin loads, has the required fields, its data parses, and
**every requirement's `target_screen` is in `scene_vocabulary`** — the most
common mistake.

## 5. Run it

```bash
python main.py --game my_game --map      # build the screen map on a connected device
python main.py --game my_game --plan     # turn requirements + map into a test plan
python main.py --game my_game            # full setup -> test cycle -> report
```

## Rules of thumb

1. Edit only files inside `src/games/<id>/`. No engine edits to add a game.
2. Locate elements by **describing them**, never by pixel coordinates.
3. Keep scene names consistent between `specs.py` and `scene_vocabulary`.
4. Multiplayer: automating one client is supported today; true two-device
   (two synchronized clients) is an advanced setup — see `DeviceSession` in
   `src/device/session.py`.
