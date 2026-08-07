# Subway Surfers plugin (endless-runner reference)

This plugin proves the framework can **play** a real-time reflex game, not just
QA menus. Menu navigation reuses the engine's VLM/OCR path; the *run* is driven
by a separate real-time stack.

## How it works

```
fast_io (scrcpy/adb)  →  perception.perceive (cv2)  →  RunnerMixin.decide  →  swipe
   frames                 LaneState                     action                fast input
```

- **`profile.py`** — `SubwaySurfers(RunnerMixin, GameProfile)`: identity, scenes,
  requirements, `read_hud` (score/coins), and `play()` (starts a run, then loops).
- **`perception.py`** — cv2 lane/obstacle detection → `LaneState`.
- **`RunnerMixin`** (`src/games/genres/runner.py`) — the loop + dodge policy.
- **`src/device/fast_io.py`** — fast capture + low-latency input.

## Setup

1. **Base deps:** `pip install -r requirements.txt` (adds `opencv-python`).
2. **Real-time backend (scrcpy).** `scrcpy-client 0.4.1` hard-pins an old `av`
   that will NOT build on Python 3.11+ (`Getting requirements to build wheel …
   Cython … av/logging.pyx` error). Install it the working way — a modern `av`
   wheel first, then scrcpy-client with `--no-deps`:

   ```bash
   pip install -r requirements-runner.txt
   pip install --no-deps scrcpy-client==0.4.1
   ```

   (Equivalently, the minimal manual form:
   `pip install --only-binary=:all: av "adbutils==0.14.1" opencv-python`
   then `pip install --no-deps scrcpy-client`.)
3. **scrcpy binary:** install the external `scrcpy` binary and put it on `PATH`
   (https://github.com/Genymobile/scrcpy). Without it, `FAST_IO_BACKEND` falls
   back to `adb` capture (~2–5 fps) — runnable for tests, **too slow to survive**.
4. **Device:** connect via ADB (`adb devices`) with Subway Surfers installed
   (`com.kiloo.subwaysurf`).

> Why the two-step install: a plain `pip install scrcpy-client` re-resolves to
> `av<10`, which has no Python 3.11 wheel and fails to compile. Installing a
> modern `av` first and scrcpy-client with `--no-deps` sidesteps the bad pin;
> scrcpy-client's decode path works fine with modern `av`.

## Run

```bash
# 1. Check the real-time backend hits its targets on your device (>=25 fps, <100ms)
python -m scripts.bench_fast_io

# 2. Validate the plugin (no device)
python -m src.games.validate subway_surfers

# 3. Build the menu map + play
python main.py --game subway_surfers --map      # map the menus (VLM/OCR)
python main.py --game subway_surfers            # navigate + play the run
```

## Calibration (the part that needs your device)

`data/calibration.json` defines the lane trapezoids and obstacle thresholds as
fractions of the frame. The shipped values are **starting points**. To tune:

1. Capture a few in-run frames on your device (`adb exec-out screencap -p > f.png`).
2. Overlay the lane bounds and the danger band; adjust `lane_near_bounds` /
   `lane_far_bounds` so the three lanes line up with the track.
3. Adjust `block_coverage` until `perceive()` flags a lane as blocked exactly when
   a train/barrier is actually there (not on coins/scenery).
4. Adjust `low_obstacle_v` / `high_obstacle_v` so low barriers → roll and overhead
   obstacles → jump.

Perception logic is unit-tested (`tests/test_subway_perception.py`); calibration
is the empirical, device-specific part.

## Notes / limits

- A run is **non-deterministic** (`RunnerMixin.nondeterministic = True`): QA
  asserts on outcomes (run started, lane changed, run ended), not a fixed route.
- Rule-based CV can survive a while; the ceiling improves with calibration and,
  if desired later, a trained model behind the same `perceive`/`decide` seam.
