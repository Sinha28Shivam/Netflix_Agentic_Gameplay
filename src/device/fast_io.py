"""
src/device/fast_io.py — real-time frame capture + low-latency input.

The default device layer (adb_utils/device.py) is built for turn-based games:
capture is ~2 fps and every tap/swipe sleeps ~1s. That is fatal for a reflex
runner (Subway Surfers), which needs ~30 fps perception and sub-100ms inputs.

This module adds a SEPARATE fast path, selected like the device backend router:

    FAST_IO_BACKEND = auto (default) | scrcpy | adb

- **scrcpy** (preferred): one connection streams decoded frames AND injects
  low-latency control. Requires the external `scrcpy` binary + the
  `scrcpy-client` Python package (imported lazily). Best real performance.
- **adb** (fallback): `exec-out screencap` decoded with cv2 + `input swipe`
  WITHOUT the 1s sleep. Works everywhere with zero setup but is only ~2-5 fps —
  usable for tests/CI and slow demos, NOT for competitive play.

Nothing here touches the existing tap/swipe/drag primitives, so Bloons and the
turn-based path are unaffected (purely additive).

Frames are numpy BGR arrays (OpenCV convention). Requires cv2 + numpy, which the
perception layer needs anyway.
"""

import subprocess
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import src.core.config as config


# ---------------------------------------------------------------- contracts
class FrameSource(ABC):
    """Produces the latest device frame as a BGR numpy array."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def read(self):
        """Return the most recent frame (H, W, 3) BGR ndarray, or None."""
        ...

    @abstractmethod
    def stop(self) -> None: ...

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


class FastControl(ABC):
    """Low-latency input — no post-gesture sleep."""

    @abstractmethod
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 80) -> None: ...

    @abstractmethod
    def tap(self, x: int, y: int) -> None: ...

    # Runner-oriented directional helpers (fractions of the screen).
    def lane_left(self, w, h):  self.swipe(int(w * 0.55), int(h * 0.6), int(w * 0.30), int(h * 0.6))
    def lane_right(self, w, h): self.swipe(int(w * 0.45), int(h * 0.6), int(w * 0.70), int(h * 0.6))
    def jump(self, w, h):       self.swipe(int(w * 0.5), int(h * 0.65), int(w * 0.5), int(h * 0.40))
    def roll(self, w, h):       self.swipe(int(w * 0.5), int(h * 0.45), int(w * 0.5), int(h * 0.70))


# ---------------------------------------------------------------- adb fallback
def _serial_args():
    return (["-s", config.DEVICE_SERIAL] if config.DEVICE_SERIAL else [])


class AdbFrameSource(FrameSource):
    """screencap→PNG→cv2.imdecode each read. ~2-5 fps. No streaming."""

    def __init__(self, serial: Optional[str] = None):
        self.serial = serial or config.DEVICE_SERIAL

    def start(self):
        return None

    def read(self):
        import cv2
        import numpy as np
        args = [config.ADB_PATH]
        if self.serial:
            args += ["-s", self.serial]
        args += ["exec-out", "screencap", "-p"]
        raw = subprocess.run(args, capture_output=True, timeout=15).stdout
        if not raw:
            return None
        buf = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)

    def stop(self):
        return None


class AdbFastControl(FastControl):
    """`input swipe`/`tap` with NO trailing sleep (unlike adb_utils)."""

    def __init__(self, serial: Optional[str] = None):
        self.serial = serial or config.DEVICE_SERIAL

    def _run(self, extra):
        args = [config.ADB_PATH]
        if self.serial:
            args += ["-s", self.serial]
        subprocess.run(args + extra, capture_output=True, timeout=10)

    def swipe(self, x1, y1, x2, y2, duration_ms: int = 80):
        self._run(["shell", "input", "swipe", str(int(x1)), str(int(y1)),
                   str(int(x2)), str(int(y2)), str(int(duration_ms))])

    def tap(self, x, y):
        self._run(["shell", "input", "tap", str(int(x)), str(int(y))])


# ---------------------------------------------------------------- scrcpy backend
class ScrcpyIO(FrameSource, FastControl):
    """Frame stream + control over one scrcpy connection. Lazy-imports the
    `scrcpy-client` package; raises a clear error if it (or the binary) is
    missing so callers can fall back to adb."""

    def __init__(self, serial: Optional[str] = None, max_fps: int = 30):
        self.serial = serial or config.DEVICE_SERIAL or None
        self.max_fps = max_fps
        self._client = None
        self._last = None

    def start(self):
        try:
            import scrcpy  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "scrcpy backend requires the 'scrcpy-client' package and the scrcpy "
                "binary. `pip install scrcpy-client` and install scrcpy, or set "
                "FAST_IO_BACKEND=adb."
            ) from e
        self._client = scrcpy.Client(device=self.serial, max_fps=self.max_fps,
                                      block_frame=True)

        def _on_frame(frame):
            if frame is not None:
                self._last = frame  # scrcpy-client yields BGR ndarrays

        self._client.add_listener(scrcpy.EVENT_FRAME, _on_frame)
        self._client.start(threaded=True)

    def read(self):
        return self._last

    def stop(self):
        if self._client is not None:
            try:
                self._client.stop()
            except Exception:
                pass

    def swipe(self, x1, y1, x2, y2, duration_ms: int = 80):
        # scrcpy control injects touch DOWN/MOVE/UP with millisecond latency.
        c = self._client.control
        steps = max(2, duration_ms // 16)
        c.touch(int(x1), int(y1), action=0)  # DOWN
        for i in range(1, steps + 1):
            xi = int(x1 + (x2 - x1) * i / steps)
            yi = int(y1 + (y2 - y1) * i / steps)
            c.touch(xi, yi, action=2)         # MOVE
            time.sleep(duration_ms / 1000.0 / steps)
        c.touch(int(x2), int(y2), action=1)   # UP

    def tap(self, x, y):
        c = self._client.control
        c.touch(int(x), int(y), action=0)
        c.touch(int(x), int(y), action=1)


# ---------------------------------------------------------------- factory
def get_fast_io(serial: Optional[str] = None) -> Tuple[FrameSource, FastControl]:
    """Return (FrameSource, FastControl) for the configured backend.
    'auto' uses scrcpy when importable, else the adb fallback."""
    backend = (getattr(config, "FAST_IO_BACKEND", "auto") or "auto").strip().lower()

    if backend in ("scrcpy", "auto"):
        try:
            import scrcpy  # noqa: F401
            io = ScrcpyIO(serial=serial)
            return io, io
        except ImportError:
            if backend == "scrcpy":
                raise RuntimeError("FAST_IO_BACKEND=scrcpy but 'scrcpy-client' is not installed.")
            # auto -> fall through to adb
            print("fast_io: scrcpy-client not installed; using slow adb fallback "
                  "(install scrcpy + scrcpy-client for real-time play).")

    return AdbFrameSource(serial=serial), AdbFastControl(serial=serial)
