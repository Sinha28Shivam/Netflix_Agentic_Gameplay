# 03 — Core Engine Subsystem Architecture & Specification

This document details the core execution engine, orchestration lifecycle, shared utilities, global configuration, and evaluation judges in **NetflixGameTestHCL**.

![Core Engine Architecture Diagram](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/images/03_core_engine.png)

---

## 1. Pipeline Orchestrator (`src/core/orchestrator.py`)

The Orchestrator coordinates system execution across setup and parallel test cycles.

### 1.1 Two-Phase Execution Pipeline

1. **Setup Phase (`setup(force: bool)`)**:
   - Checks if valid non-empty `map_store.json` and `test_plan.json` exist.
   - If missing or `force=True`, triggers `MapAgent().build_map()` and `PlannerAgent().build_plan()`.
   - Ensures new games map once and subsequent runs jump straight to testing.

2. **Test Cycle Phase (`run_cycle_and_report()`)**:
   - Launches main gameplay execution via `ExecutorAgent` in the primary thread.
   - Spawns concurrent daemon threads:
     - `_PerfWorker`: Periodic hardware monitoring (FPS, CPU %, RAM MB).
     - `_ComplianceWorker`: Screen snapshot capture & parallel regulatory compliance checks.
   - Collects cycle evidence into shared memory and invokes `ValidatorAgent`.

---

## 2. Shared Utilities (`src/core/qa_common.py`)

`qa_common.py` is the foundational perception and interaction library across all agents.

### 2.1 Key Perception & VLM Functions
- **`screencap(dst_path)`**: Captures device screen via ADB/Appium and saves to local disk.
- **`ocr_all(img_path)`**: Performs OCR word and bounding box extraction using Tesseract.
- **`vlm_locate(img_path, prompt)`**: Queries Google Gemini / Claude VLM with natural language descriptions to return normalized `(x, y)` UI target coordinates.
- **`screen_signature(tokens, scene)`**: Generates unique visual fingerprints combining scene tags, token hashes, and perceptual pixel hashes.
- **`solidly_in_match(img_path)`**: Deterministic HUD verifier (evaluates round indicators and currency counters to confirm active gameplay vs menu screens).

### 2.2 Device Helper Functions
- **`tap(x, y)`**: Sends tap input via configured backend.
- **`wait_stable()` / `wait_not_loading()`**: Condition-driven UI stabilization waiting (no hardcoded fixed sleep cap).
- **`clear_popups()`**: Automatically detects and dismisses system dialogs, rate-us popups, and reward banners.

---

## 3. Configuration Management (`src/core/config.py`)

All global parameters are centralized in `config.py` with `.env` file support and automatic fallback defaults:

- **Hardware & Device**: `ADB_PATH` (auto-resolved across Windows SDK paths), `DEVICE_SERIAL`, `EXECUTION_MODE` (`adb` vs `appium`), `FAST_IO_BACKEND` (`scrcpy` vs `adb`).
- **Game Identity**: `GAME_ID`, `GAME_PACKAGE`, `GAME_ACTIVITY`.
- **LLM / VLM API**: `LLM_API_KEY`, `VISION_MODEL` (`claude-3-5-sonnet-20241022`), `LLM_BASE_URL`.
- **File System Paths**: `LOG_DIR`, `OUTPUT_DIR`, `MAP_FILE`, `PLAN_FILE`, `RESULTS_FILE`.

---

## 4. Shared State & Memory (`src/core/memory.py`)

- **`MemoryStore`**: Thread-safe in-memory cache tracking screen transition histories, past action attempts, VLM failure points (to prevent repetitive mis-taps), and aggregated test run statistics.

---

## 5. Execution Engine & Verification Judges (`src/core/engine/`)

### 5.1 TestRunner (`test_runner.py`)
- Executes individual test steps defined in `test_plan.json`.
- Manages action dispatching, step retries, and timeout enforcement.

### 5.2 VerificationJudge (`verification_judge.py`)
- Implements verification logic comparing pre-action and post-action screen states.
- Uses multi-modal checks (OCR text delta, visual pixel change, HUD numeric updates) to confirm step completion.
