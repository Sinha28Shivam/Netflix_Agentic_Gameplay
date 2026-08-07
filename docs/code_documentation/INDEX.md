# Netflix Game Test HCL — Detailed Code Documentation Index

Welcome to the comprehensive code documentation suite for **NetflixGameTestHCL** (Netflix Game Test Automation POC).

This document serves as the master index and navigation hub across all subsystem technical documentation files.

---

## 📚 Documentation Table of Contents

1. [Architectural Overview](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/01_architecture_overview.md)
   - High-Level Architecture & Multi-Agent Design
   - System Lifecycle & Stage Pipeline
   - Environment Configuration & Folder Hierarchy
   - Dataflow & Inter-Agent Messaging Contracts

2. [Agents Subsystem](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/02_agents_subsystem.md)
   - Planning Agents (`MapAgent`, `PlannerAgent`)
   - Core Agents (`VisionAgent`, `DecisionAgent`, `OracleAgent`)
   - Execution Agents (`ExecutorAgent`, `PerformanceAgent`, `RecoveryAgent`)
   - Compliance Agents (`ComplianceAgent`, `ComplianceOracle`)
   - Evaluation Agents (`ValidatorAgent`, `ReportAgent`)

3. [Core Engine Subsystem](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/03_core_engine.md)
   - Pipeline Orchestrator (`orchestrator.py`)
   - QA Common Utility Layer (`qa_common.py`)
   - Configuration Management (`config.py`)
   - Shared Memory & State Tracking (`memory.py`)
   - Test Runner Engine (`src/core/engine/test_runner.py`)
   - Verification Judge (`src/core/engine/verification_judge.py`)

4. [Device Automation & Platform Abstraction](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/04_device_automation.md)
   - Device Abstraction Layer (`device.py`, `session.py`)
   - Appium Integration (`appium_utils.py`)
   - Fast I/O & Low-Latency Touches (`fast_io.py`)
   - Android ADB Utilities (`src/device/android/adb_utils.py`)
   - iOS & Web Driver Placeholders
   - Performance Monitoring (`perf_utils.py`)

5. [Games Integration Subsystem](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/05_games_integration.md)
   - Plugin Architecture & Game Registry (`registry.py`)
   - Base Game Abstraction (`base.py`)
   - Genre Adapters (`runner.py`, `pvp.py`, `tower_defense.py`)
   - Game Implementations (`Bloons TD 6`, `Subway Surfers`, `Example PvP`)
   - Plugin Generator & Validator (`new.py`, `validate.py`)

6. [Reinforcement Learning (RL) Engine](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/06_reinforcement_learning.md)
   - Custom Gym Environment Wrapper (`env.py`)
   - Markov Decision Process Formulation (`mdp.py`)
   - Q-Learning Agent & Q-Table Persistence (`qlearning.py`)
   - Reward Shaping & Metrics (`reward.py`)
   - RL Decision Integration (`rl_decision_agent.py`)
   - Standalone RL Trainer (`train.py`)

7. [Data Models, Specs, & Execution Entry Points](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/07_models_and_configs.md)
   - Map Store & UI Node Graphs (`map_store.py`, `map_store.json`)
   - Gameplay Verification Checks & Descriptions (`gameplay_checks.py`, `gameplay_descriptions.py`)
   - Scenarios & Category Specifications (`scenarios.py`, `category_specs.py`)
   - CLI Entry Point & Pipeline Options (`main.py`)
   - Utility Scripts (`scripts/`) & Test Suite (`tests/`)

---

## 🚀 Quick Execution Quickstart

To run the full end-to-end agentic QA pipeline:
```bash
python main.py --game bloons_td6
```

To run individual stages:
```bash
python main.py --map      # Stage 1: Exploration & Mapping
python main.py --plan     # Stage 2: Test Plan Generation
python main.py --execute  # Stage 3: Parallel Gameplay & Compliance Execution
python main.py --report   # Stage 4: HTML & JSON Report Generation
```
