# 01 — System Architecture & Multi-Agent Design Overview

This document describes the high-level architecture, design principles, multi-agent orchestration, lifecycle, and data flow of the **NetflixGameTestHCL** (Netflix Game Test Automation POC) platform.

---

## 1. High-Level Architecture

The platform provides autonomous, vision-and-LLM-driven Quality Assurance (QA) and compliance testing for mobile/web games (such as *Bloons TD 6*, *Subway Surfers*, and competitive multiplayer/PvP titles).

![Architecture Overview Diagram](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/images/01_architecture_overview.png)

```
                      +----------------------------------+
                      |         CLI / Entry Point        |
                      |            (main.py)             |
                      +----------------------------------+
                                       |
                                       v
                      +----------------------------------+
                      |       Pipeline Orchestrator      |
                      |     (src/core/orchestrator.py)   |
                      +----------------------------------+
                                       |
                  +--------------------+--------------------+
                  |                                         |
                  v (If new game)                           v (Every test cycle)
       +-----------------------+               +-----------------------+
       |   SETUP PHASE (1 & 2) |               |  PARALLEL TEST CYCLE  |
       |                       |               |       (STAGE 3)       |
       |  MapAgent -> Planner  |               |  ExecutorAgent (Main) |
       +-----------------------+               |   ├── PerfWorker      |
                  |                            |   └── ComplianceWorker|
                  v                            +-----------------------+
        [map_store.json]                                    |
        [test_plan.json]                                    v
                                               +-----------------------+
                                               |    STAGE 4: EVAL      |
                                               | Validator & Recovery  |
                                               |     ReportAgent       |
                                               +-----------------------+
                                                            |
                                                            v
                                                    [results.json]
                                                    [HTML Report]
```

---

## 2. Execution Stages & Lifecycle

The architecture operates in **4 strict stages**, divided into a one-time **Setup Phase** and a recurring **Test Cycle Phase**:

### Setup Phase (Runs ONCE per new game)
1. **Stage 1: Exploration & Mapping (`MapAgent`)**
   - Autonomously traverses the game's UI hierarchy (menus, age gate, settings, store, level select).
   - Generates a graph representation (`map_store.json`) mapping UI screens, bounding boxes, buttons, text elements, and navigation edges.

2. **Stage 2: Test Planning (`PlannerAgent`)**
   - Reads `map_store.json` alongside game specifications (`specs.py` / `scenarios.py`).
   - Generates an actionable, ordered execution script (`test_plan.json`) containing test steps, expected UI targets, gameplay scenarios, and compliance probes.

### Test Cycle Phase (Runs on EVERY pipeline run)
3. **Stage 3: Parallel Execution & Verification (`ExecutorAgent`)**
   - **Main Gameplay Thread**: Executes navigation and gameplay actions on the target device via Appium/ADB/Fast-IO.
   - **Performance Worker Thread (`_PerfWorker`)**: Concurrently monitors hardware metrics (FPS, RAM usage in MB, CPU % load, jank frames).
   - **Compliance Worker Thread (`_ComplianceWorker`)**: Concurrently captures distinct screen snapshots and evaluates legal/regulatory compliance (age gate presence, ESRB ratings, IAP price disclosures, Netflix brand guidelines).

4. **Stage 4: Validation, Healing, & Reporting**
   - **`ValidatorAgent`**: Evaluates raw execution artifacts against expected criteria, outputting pass/fail/inconclusive metrics.
   - **`RecoveryAgent`**: Diagnoses crashes, popups, or frozen states; self-heals by restarting app sessions or clearing popups.
   - **`ReportAgent`**: Consolidates results, logs, and screenshots into JSON (`outputs/results/results.json`) and styled HTML reports.

---

## 3. Directory Layout & Subsystem Structure

```
NetflixGameTestHCL/
├── main.py                     # Primary CLI launcher & stage coordinator
├── requirements.txt            # Python dependencies (Appium, OpenCV, Gym, Gemini API)
├── docs/                       # Architectural documentation & guides
│   └── code_documentation/     # Exhaustive subsystem technical docs
├── src/                        # Core codebase
│   ├── agents/                 # Specialized autonomous agents
│   │   ├── compliance/         # Compliance rules & vision verification
│   │   ├── core/               # Decision, Vision, & Oracle foundational agents
│   │   ├── evaluation/         # Validator & HTML Report generator agents
│   │   ├── execution/          # Gameplay Executor, Perf, & Recovery agents
│   │   └── planning/           # UI Mapper & Test Planner agents
│   ├── core/                   # Central runtime & engine
│   │   ├── engine/             # TestRunner & VerificationJudge
│   │   ├── orchestrator.py     # Main cycle & thread orchestration
│   │   ├── qa_common.py        # OCR, VLM vision client, UI helpers
│   │   ├── config.py           # Global settings & thresholds
│   │   └── memory.py           # Execution state & history store
│   ├── device/                 # Hardware & Platform abstraction
│   │   ├── device.py           # Generic device driver interface
│   │   ├── appium_utils.py     # Appium session manager
│   │   ├── fast_io.py          # Low-latency touch/swipe engine
│   │   ├── session.py          # Session lifecycle & screenshot capturing
│   │   └── android/adb_utils.py# Direct ADB fallback & performance metrics
│   ├── games/                  # Game integration plugins
│   │   ├── base.py             # Abstract base class for game profiles
│   │   ├── registry.py         # Plugin discovery & lookup registry
│   │   ├── bloons_td6/         # Bloons TD 6 game adapter
│   │   ├── subway_surfers/     # Subway Surfers game adapter
│   │   ├── genres/             # Generic genre adapters (Runner, PvP, Tower Defense)
│   │   └── new.py / validate.py# Plugin generator & validator utilities
│   ├── models/                 # Data schemas & verification specs
│   │   └── map_store.py        # Map store data loader & graph queries
│   └── rl/                     # Reinforcement Learning gameplay engine
│       ├── env.py              # OpenAI/Farama Gym interface wrapper
│       ├── mdp.py              # State/Action space & reward definition
│       ├── qlearning.py        # Q-Learning agent with tabular persistence
│       └── train.py            # Standalone RL training loop
└── outputs/                    # Runtime artifacts
    ├── logs/                   # Detailed execution logs & screenshot probes
    └── results/                # map_store.json, test_plan.json, results.json
```

---

## 4. Multi-Agent Interaction & Data Flow

```
+-----------------------------------------------------------------------------------+
|                                  DATAFLOW PIPELINE                                |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  [Game App] <---> [Device Abstraction Layer (Appium/ADB/Fast-IO)]                 |
|                            ^                      ^                               |
|                            |                      |                               |
|                     (Touch / Swipe)        (Screenshots / Perf)                   |
|                            |                      |                               |
|                     +--------------+      +------------------+                    |
|                     | ExecutorAgent|      | ComplianceWorker |                    |
|                     +--------------+      +------------------+                    |
|                            |                      |                               |
|                            v                      v                               |
|                 +------------------------------------+                            |
|                 |       Shared Memory & State        |                            |
|                 +------------------------------------+                            |
|                                    |                                              |
|                                    v                                              |
|                 +------------------------------------+                            |
|                 |     ValidatorAgent / Judge         |                            |
|                 +------------------------------------+                            |
|                                    |                                              |
|                                    v                                              |
|                 +------------------------------------+                            |
|                 |     ReportAgent (HTML / JSON)      |                            |
|                 +------------------------------------+                            |
+-----------------------------------------------------------------------------------+
```

---

## 5. Key System Capabilities

- **Zero-Hardcoding Vision Automation**: Combines Tesseract OCR and Google Gemini VLM (Vision Language Model) to locate UI elements dynamically based on text or natural language intent.
- **Low-Latency Direct Touch I/O**: `fast_io.py` bypasses high-overhead Appium HTTP calls for fast-paced arcade games like *Subway Surfers* using direct OS socket inputs or low-level ADB input streams.
- **Modular Game Plugins**: Simple, template-driven integration system (`base.py` + `registry.py`) allowing new games to be added in minutes.
- **Tabular Q-Learning Engine**: Integrated Gym environment wrapper permitting RL agents to learn gameplay policies directly from screen states and game rewards.
