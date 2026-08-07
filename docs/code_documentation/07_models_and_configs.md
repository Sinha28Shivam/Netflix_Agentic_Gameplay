# 07 — Data Models, Specifications, Scripts & Test Suite

This document covers data models, JSON schemas, map graph persistence, verification checks, CLI entry points, utility scripts, and test suite execution in **NetflixGameTestHCL**.

![Data Models & Configs Diagram](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/images/07_models_and_configs.png)

---

## 1. Map Store Data Model (`src/models/map_store.py`)

The `MapStore` class provides graph persistence for UI navigation states:

### 1.1 Core Data Classes
- **`ScreenNode`**: Represents a unique screen UI node.
  - `screen_id`: Unique identifier string (e.g. `main_menu`, `difficulty_select`).
  - `label`: Human-readable title tag.
  - `sample_ui_texts`: List of extracted OCR tokens.
  - `actionable_elements`: Array of clickable UI targets.
  - `tags`: Node category labels (e.g., `["compliance_relevant"]`).
- **`TransitionEdge`**: Directed edge between UI nodes.
  - `from_screen`: Origin node ID.
  - `to_screen`: Destination node ID.
  - `action`: Executed target payload (e.g., `{"action": "tap", "target": "Play"}`).

### 1.2 Serialization Target (`outputs/results/map_store.json`)
Stores the complete graph per game so the `PlannerAgent` can compute path transitions offline without redundant UI re-exploration.

---

## 2. Verification Specs & Models (`src/models/`)

- **`gameplay_checks.py`**: Central registry of assertion check functions (`check_in_match`, `check_hud_updated`, `check_tower_placed`).
- **`category_specs.py`**: Taxonomical definitions for compliance categories (Age Ratings, Pricing, Legal Disclaimer, Brand Logos).
- **`scenarios.py`**: Pre-configured test scenario definitions for supported game genres.
- **`objectives.py`**: Mappings between screen states and high-level agent objectives.

---

## 3. CLI Entry Point (`main.py`)

`main.py` is the CLI coordinator implementing stage flags:

```bash
python main.py [--game GAME_ID] [--map] [--plan] [--execute] [--report] [--force-setup]
```

### CLI Command Options
- `--game`: Select active game profile (default: `bloons_td6`).
- `--force-setup`: Force re-execution of Stage 1 (Mapper) and Stage 2 (Planner) even if `map_store.json` exists.
- `--map`: Run Stage 1 (Map) only.
- `--plan`: Run Stage 2 (Plan) only.
- `--execute`: Run Stage 3 (Parallel execution cycle) only.
- `--report`: Run Stage 4 (Report compilation) only.

---

## 4. Utility Scripts (`scripts/`)

- **`map_and_plan.py`**: Standalone script to trigger Mapper and Planner stages sequentially.
- **`run_plan.py`**: Standalone executor to run an existing `test_plan.json` against a target device.
- **`rl_navigate.py`**: Standalone launcher for RL agent navigation evaluation.
- **`check_drag.py`**: Diagnostic utility for testing low-level drag/swipe input contracts on physical devices.
- **`bench_fast_io.py`**: Benchmarking script for measuring FPS frame rates and gesture latency on direct I/O streams.

---

## 5. Test Suite (`tests/`)

The repository includes pytest-compatible automated unit and integration tests:

| Test Script | Description |
| :--- | :--- |
| `tests/smoke_test.py` | Validates environment imports, config loading, and ADB path resolution. |
| `tests/test_api.py` | Tests basic API connectivity and model response handling. |
| `tests/test_compliance_split.py` | Tests compliance rule evaluation and evidence payload generation. |
| `tests/test_drag_contract.py` | Tests touchscreen drag coordinate interpolation and gesture contracts. |
| `tests/test_map_and_plan.py` | Verifies end-to-end MapAgent traversal and PlannerAgent output schemas. |
| `tests/test_registry.py` | Tests game plugin registration, discovery, and lookup functions. |
| `tests/test_rl.py` | Verifies Gym environment wrappers, MDP state transitions, and Q-learning updates. |
| `tests/test_runner_dispatch.py` | Tests action dispatching and TestRunner execution contracts. |
| `tests/test_runner_genre.py` | Tests genre-specific mixins (Tower Defense, Runner, PvP). |
| `tests/test_subway_perception.py` | Tests OpenCV frame processing and lane detection for Subway Surfers. |

### Running the Test Suite
```bash
pytest tests/
```
