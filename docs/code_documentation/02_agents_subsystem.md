# 02 — Agents Subsystem Architecture & Specification

This document details all autonomous agents in the **NetflixGameTestHCL** ecosystem, organized by operational phase: **Planning**, **Core Perception & Decision**, **Execution & Recovery**, **Compliance**, and **Evaluation & Reporting**.

![Multi-Agent Subsystem Diagram](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/images/02_agents_subsystem.png)

---

## 1. Planning Agents (`src/agents/planning/`)

### 1.1 MapAgent (`map_agent.py`)
- **Role**: Autonomous UI explorer and scene graph builder (Stage 1).
- **Key Methods**:
  - `build_map()`: Main execution entry point. Runs `seed_from_walkthrough()` followed by `explore_gaps()`.
  - `seed_from_walkthrough()`: Replays generic walkthrough steps (e.g., age gate, play button, difficulty selection) via OCR and VLM fallback without hardcoded coordinates.
  - `explore_gaps()`: Systematically discovers unmapped screens and unvisited actionable elements on candidate nodes.
- **Output Artifacts**:
  - `outputs/results/map_store.json`: Serialized UI graph of screen IDs, scene tags (`home`, `title`, `difficulty_select`, `in_game`), OCR tokens, and navigation transitions.

### 1.2 PlannerAgent (`planner_agent.py`)
- **Role**: Test plan generator (Stage 2).
- **Key Methods**:
  - `build_plan()`: Reads `map_store.json` and active game scenarios/specs to produce a comprehensive list of actionable test cases.
  - `_build_compliance_specs()`: Derives compliance test specs (e.g., age rating display, IAP disclosures, splash screen branding).
  - `_build_gameplay_tasks()`: Maps game difficulty paths and target scenes to game objectives.
- **Output Artifacts**:
  - `outputs/results/test_plan.json`: Ordered test execution pipeline containing setup steps, gameplay objectives, and compliance probe specs.

---

## 2. Core Agents (`src/agents/core/`)

### 2.1 VisionAgent (`vision_agent.py`)
- **Role**: Multi-modal visual processing and screen understanding agent.
- **Key Capabilities**:
  - Integrates Tesseract OCR for text extraction and Gemini VLM for semantic visual localization (`vlm_locate`).
  - Implements screen signature generation (`screen_signature`) and visual similarity distance checks using perceptual hashing (`_pixel_hash`).

### 2.2 DecisionAgent (`decision_agent.py`)
- **Role**: High-level action selection and fallback policy manager.
- **Key Capabilities**:
  - Decides whether to issue OCR taps, VLM taps, or RL policy actions based on current scene state and objective goals.
  - Coordinates recovery fallback strategies when expected screen transitions fail to materialize.

### 2.3 OracleAgent (`oracle_agent.py`)
- **Role**: Dynamic truth provider and screen evaluator.
- **Key Capabilities**:
  - Evaluates screen states against game invariants and compliance rules.
  - Validates whether an action successfully caused expected state transitions.

---

## 3. Execution Agents (`src/agents/execution/`)

### 3.1 ExecutorAgent (`executor_agent.py`)
- **Role**: Main gameplay execution driver (Stage 3).
- **Key Entry Points**:
  - `navigate(target_scene, ...)`: Traverses the UI node graph in `map_store.json` from the current screen to the `target_scene`.
  - `play(scenario, duration_s, ...)`: Drives gameplay execution (unit placement, path navigation, speed toggles) using game profiles and genre adapters.
- **Key Features**:
  - Integrates direct game loop controls (`src/games/`).
  - Manages clear popup logic (`clear_popups()`) and loading screen detection (`wait_not_loading()`).

### 3.2 PerformanceAgent (`performance_agent.py`)
- **Role**: Concurrent hardware metric sampling node.
- **Key Methods**:
  - `sample(scene_name)`: Captures FPS, RAM usage (MB), CPU %, and jank frame metrics via direct ADB dumpsys calls (`adb_utils.py`).
  - Summarizes performance stats per scene for inclusion in the final report.

### 3.3 RecoveryAgent (`recovery_agent.py`)
- **Role**: Automated self-healing and error recovery agent.
- **Key Capabilities**:
  - Detects app crashes, frozen states, or unhandled dialogs.
  - Executes force-stops (`force_stop`), re-launches app packages (`launch_game`), and restores execution state to previous valid nodes.

---

## 4. Compliance Agents (`src/agents/compliance/`)

### 4.1 ComplianceAgent (`compliance_agent.py`)
- **Role**: Legal, branding, and regulatory compliance inspection node.
- **Key Capabilities**:
  - Evaluates screen snapshots against rule specifications (Age Ratings, ESRB icons, Terms of Service, In-App Purchase pricing, Netflix branding).
  - Combines deterministic OCR matching with VLM model judgments for ambiguous visual assets.

### 4.2 ComplianceOracle (`compliance_oracle.py`)
- **Role**: Compliance rule evaluation engine and verification scoring.
- **Key Capabilities**:
  - Verifies presence of required legal disclaimers.
  - Generates detailed pass/fail evidence payloads with cropped screenshot bounding boxes.

---

## 5. Evaluation & Reporting Agents (`src/agents/evaluation/`)

### 5.1 ValidatorAgent (`validator_agent.py`)
- **Role**: Test suite verdict engine (Stage 4).
- **Key Methods**:
  - `validate_cycle(...)`: Aggregates gameplay execution results, performance metrics, and compliance evidence.
  - Assigns final verdicts (`PASS`, `FAIL`, `INCONCLUSIVE`) for each planned test case based on strict validation thresholds.

### 5.2 ReportAgent (`report_agent.py`)
- **Role**: Report compiler and HTML documentation generator (Stage 4).
- **Key Methods**:
  - `generate_report()`: Compiles all results into `outputs/results/results.json` and a visually styled standalone HTML report containing execution metrics, logs, performance charts, and annotated screenshot evidence.
