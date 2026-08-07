# Netflix Game QA — Agentic Pipeline

Automated QA for Netflix mobile games on Android via ADB + VLM (Claude, native Anthropic API).

> 📖 **Complete Technical Code Documentation**: See [docs/code_documentation/INDEX.md](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/INDEX.md) for full subsystem documentation, API contracts, multi-agent workflows, and architectural guides.

## Architecture

```
seed_scripts/bloons_seed.json  specs.json
         |                         |
   [Stage 1: MAP]           [Stage 2: PLAN]
   MapAgent                  PlannerAgent
   map_store.json ---------> test_plan.json
                                    |
                           [Stage 3: EXECUTE]
                           ExecutorAgent
                           results.json  +  logs/
```

All three stages share `config.py`, `agents/qa_common.py` (OCR + VLM), and
`device/adb_utils.py` (ADB). No hardcoded coordinates anywhere — every element is
located by describing it to the VLM in natural language.

## Quick start

```bash
# 0. Install dependencies
pip install -r requirements.txt

# 1. Connect an Android device with ADB and the game installed
#    Edit ADB_PATH / LLM_API_KEY in config.py (or set env vars)

# 2. Run the full pipeline (setup once per new game, then the parallel
#    gameplay/compliance/performance cycle, then validate + report)
python main.py

# 3. Force Mapper+Planner to re-run even if the game is already mapped
python main.py --force-setup

# 4. Run stages individually
python main.py --map      # Stage 1: builds map_store.json
python main.py --plan     # Stage 2: builds test_plan.json
python main.py --execute  # Stage 3: runs the parallel test cycle, writes results.json
python main.py --report   # Stage 4: builds the HTML report from results.json
```

## Project layout

```
config.py                   Central configuration (ADB, LLM, game constants)
main.py                     Pipeline entrypoint (--map / --plan / --execute / --report / --force-setup)
orchestrator.py             Setup-once + parallel test cycle + validate + self-heal + report
specs.json                  Test requirements (compliance / performance / gameplay)
seed_scripts/
  bloons_seed.json          Navigation seed for Bloons TD 6
agents/
  qa_common.py              OCR, VLM locate, logging, screen-change detection
  gameplay_descriptions.py  Natural-language element descriptions (shared, no coords)
  scenarios.py              In-match test scenarios T2–T10
  map_agent.py              Stage 1 — builds map_store.json + MapStore graph
  planner_agent.py          Stage 2 — specs + map -> test_plan.json
  executor_agent.py         Stage 3 — runs test_plan.json on device
  vision_agent.py           VLM scene + element perception (for orchestrator loop)
  decision_agent.py         Action selection
  compliance_agent.py       Netflix compliance checks
  performance_agent.py      FPS / memory / load-time
  recovery_agent.py         Stuck-loop recovery
  oracle_agent.py           Gameplay pass/fail oracle
  validator_agent.py        Turns cycle evidence into per-spec PASS/FAIL/PARTIAL/INCONCLUSIVE
  report_agent.py           Writes the final HTML report
  map_store.py              Screen graph storage + Dijkstra path queries
device/
  adb_utils.py              All ADB primitives (tap, swipe, screencap, launch…)
  perf_utils.py             Performance sampling helpers
tests/                      Unit tests + smoke test (run with python -m pytest tests/)
maps/                       MapStore JSON files (one per game)
plans/                      Per-game test plan JSON files
reports/                    Final QA report JSON files
logs/                       Per-run log + timestamped screenshots
```

See `ARCHITECTURE_MAP.md` for how each diagram box maps to code and what's
still stubbed vs built.

## Configuration

All settings live in `config.py`. Key variables:

| Variable | Default | Notes |
|---|---|---|
| `ADB_PATH` | Auto-resolved from `PATH`/SDK dirs | Override via `ADB_PATH` env var |
| `LLM_API_KEY` | — (must be set) | Set via `LLM_API_KEY` env var; do not hardcode |
| `LLM_BASE_URL` | `https://api.anthropic.com/v1` | Override via `LLM_BASE_URL` env var (Bedrock/Vertex/proxy) |
| `VISION_MODEL` | `claude-opus-4-8` | Model name for VLM calls |
| `GAME_PACKAGE` | `com.netflix.NGP.BloonsTDSix` | Target game |
| `PLAY_MINUTES` | `10` | Max playthrough duration |
| `DART_COST` | `170` | Dart Monkey cost on Easy |
| `CASH_RESERVE` | `150` | Minimum cash to keep |

## Test scenarios

| ID | Description |
|---|---|
| T1 | Title navigation & profile handshake |
| T2 | Sidebar carousel navigation |
| T3 | Drag-and-drop placement validity (path reject + grass accept) |
| T4 | Target priority adjustment |
| T5 | Upgrade path branching |
| T6 | Battle speed toggle (fast-forward) |
| T7 | Cooldown / hero ability synchronization |
| T8 | Sell & replace infrastructure |
| T9 | Defeat modal interaction |
| T10 | Notification / popup handling |
