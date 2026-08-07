# 04 — Device Automation & Platform Abstraction Architecture

This document describes the device abstraction layer, input routing, hardware interaction primitives, high-rate I/O engine, and performance monitoring utilities in **NetflixGameTestHCL**.

![Device Automation Architecture Diagram](file:///c:/Users/sinha/Desktop/Netflix_POC_Details/NetflixGameTestHCL/docs/code_documentation/images/04_device_automation.png)

---

## 1. Unified Device Interface Router (`src/device/device.py`)

To ensure full portability between local debugging, CI pipelines, and real device farms, all agent interactions pass through `src/device/device.py`.

### 1.1 Backend Switch Matrix
- Controlled via environment configuration: `EXECUTION_MODE = adb` (default) or `EXECUTION_MODE = appium`.
- Automatically binds identical function signatures regardless of the selected backend:
  ```python
  from src.device.device import (
      tap, back, swipe, drag, force_stop, launch_game,
      screencap, get_screenshot_base64, get_ui_texts, get_screen_size
  )
  ```

---

## 2. Platform Drivers

### 2.1 Android ADB Engine (`src/device/android/adb_utils.py`)
- **Direct Subprocess Operations**: Wraps `adb.exe` commands with automatic serial routing (`-s <DEVICE_SERIAL>`).
- **Touch Primitives**:
  - `tap(x, y)`: Issues `adb shell input tap x y` followed by settle delay.
  - `swipe(x1, y1, x2, y2, duration_ms)`: Issues `adb shell input swipe`.
  - `drag(x1, y1, x2, y2, duration_ms)`: Smooth drag sequence with interpolation.
- **App Control**: `force_stop(package)`, `launch_game(package, activity)`.
- **UI Dump**: `get_ui_texts()` dumps UI hierarchy via `uiautomator dump` to parse accessibility node strings.

### 2.2 Appium Driver (`src/device/appium_utils.py`)
- **Session Lifecycle**: Manages WebDriver connection to local or remote Appium servers (`APPIUM_SERVER_URL`).
- **W3C Actions API**: Performs multitouch, drag-and-drop, and swipe gestures via W3C Action Chains.
- **Fallback Integration**: Leverages direct ADB calls for raw binary operations (e.g. `dumpsys` performance profiling) while routing UI actions through Appium.

### 2.3 iOS & Web Extensions (`src/device/ios/`, `src/device/web/`)
- Directory structure pre-configured with package initialization hooks (`__init__.py`) to support XCUITest (iOS) and Selenium/Playwright (Web) driver extensions.

---

## 3. High-Rate Real-Time I/O Engine (`src/device/fast_io.py`)

Turn-based game actions (~1-2 FPS) are insufficient for fast-paced reflex runner games like *Subway Surfers* (which require 30 FPS visual processing and sub-100ms inputs).

`fast_io.py` provides a high-rate I/O pipeline selected via `FAST_IO_BACKEND`:

1. **`scrcpy` Backend (Preferred)**:
   - Streams raw H.264 video frames directly over TCP/sockets.
   - Decodes to BGR OpenCV matrices at ~30–60 FPS.
   - Injects control input events directly over the control socket with near-zero latency.

2. **`AdbFrameSource` / `AdbFastControl` (Fallback)**:
   - Reads raw frames via `adb exec-out screencap -p` decoded directly into OpenCV buffers without disk I/O.
   - Issues immediate input swipes omitting artificial sleep delays.

---

## 4. Performance Profiling (`src/device/perf_utils.py`)

Monitors hardware performance indicators while tests execute:

- **FPS & Jank Diagnostics**: Executes `adb shell dumpsys gfxinfo <package>` to calculate frame rates and jank ratios (>16.6ms frame render times).
- **RAM Memory Allocation**: Executes `adb shell dumpsys meminfo <package>` to extract PSS (Proportional Set Size) total RAM usage in MB.
- **CPU Utilization**: Parses `adb shell top -n 1` output to monitor per-core and aggregate CPU load percentages.
