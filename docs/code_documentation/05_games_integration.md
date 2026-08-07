# 05 — Games Integration Subsystem & Plugin Architecture

This document details the game plugin architecture, abstract `GameProfile` interfaces, genre adapters, game registry, plugin generation tooling, and validation framework in **NetflixGameTestHCL**.

![Games Integration Architecture Diagram](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/images/05_games_integration.png)

---

## 1. Plugin Architecture & Registry (`src/games/registry.py`)

The platform implements a plug-and-play architecture for games. New games register themselves dynamically at import time using the `@register` decorator.

```python
from src.games.registry import register, get_game, available_games
from src.games.base import GameProfile

@register
class BloonsTD6Game(GameProfile):
    game_id = "bloons_td6"
    display_name = "Bloons TD 6"
    package = "com.netflix.NGP.BloonsTDSix"
```

- **`get_game(game_id)`**: Instantiates and returns the active `GameProfile`.
- **`available_games()`**: Returns a sorted list of all registered game IDs.

---

## 2. Base Game Interface (`src/games/base.py`)

All game integrations inherit from `GameProfile` (directly or via genre mixins):

### Required Attributes & Methods
- **Identity**: `game_id`, `display_name`, `package`, `activity`.
- **Goal & Mission**: `mission_summary`, `goal` dictionary.
- **Scene Vocabulary**: List of screen tags (`loading`, `main_menu`, `difficulty_select`, `in_game`, `victory`, `defeat`).
- **`build_requirements()`**: Returns a list of `RequirementSpec` objects defining test objectives.

### Overridable Hooks
- **`element_descriptions()`**: Dictionary of natural language visual prompts for VLM target localization.
- **`read_hud(png_path)`**: Game-specific HUD parsing (round count, health, money/coins).
- **`gameplay_check_registry()`**: Custom verification logic functions for step assertion.
- **`is_goal_reached(state)`** / **`is_terminal(state)`**: Evaluates whether current state completes objective or signals game over.

---

## 3. Genre Adapters (`src/games/genres/`)

Genre adapters standardize common mechanics so individual games only supply screen layout mappings:

### 3.1 Tower Defense Adapter (`tower_defense.py`)
- Provides `TowerDefenseMixin`.
- Defines unit placement grids, wave progression verification, cash/income monitoring, and speed toggle controls.

### 3.2 Endless Runner Adapter (`runner.py`)
- Provides `RunnerMixin`.
- Handles continuous fast I/O control loops (`lane_left`, `lane_right`, `jump`, `roll`), obstacle avoidance, and game over restart triggers.

### 3.3 Competitive PvP Adapter (`pvp.py`)
- Provides `PvPMixin`.
- Controls matchmaking state machines, opponent loading timers, turn transitions, and end-of-match leaderboard parsing.

---

## 4. Game Implementations

1. **`bloons_td6/`**: Full implementation for *Bloons TD 6* (Tower Defense). Defines map scenarios, hero selection steps, tower placement presets, and HUD verification.
2. **`subway_surfers/`**: Implementation for *Subway Surfers* (Endless Runner). Integrated with high-fps fast I/O frame capture and visual lane tracking (`perception.py`).
3. **`example_pvp/`**: Reference implementation demonstrating multi-player / PvP turn state tracking.

---

## 5. Plugin CLI Tooling (`new.py` & `validate.py`)

### 5.1 Plugin Generator (`python -m src.games.new <game_id>`)
- Automatically scaffolds a new game plugin directory under `src/games/<game_id>/` populated with template files:
  - `profile.py` (inheriting from `GameProfile`)
  - `specs.py`, `scenarios.py`, `descriptions.py`
  - `data/map_seed.json`

### 5.2 Plugin Validator (`python -m src.games.validate <game_id>`)
- Runs automated compliance checks against a new game plugin to verify required attributes, valid data JSON schemas, non-empty scene vocabulary, and valid requirement specs.
