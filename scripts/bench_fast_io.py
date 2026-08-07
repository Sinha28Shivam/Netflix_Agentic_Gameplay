"""
Benchmark the fast-I/O backend on a connected device.

    python -m scripts.bench_fast_io               # auto backend
    FAST_IO_BACKEND=adb python -m scripts.bench_fast_io

Reports capture FPS (target >= 25) and swipe round-trip latency (target < 100ms).
Requires an attached device. Does NOT need any specific game running.
"""

import time

from src.device.fast_io import get_fast_io


def main():
    src, ctrl = get_fast_io()
    src.start()
    try:
        # warm up
        for _ in range(3):
            src.read()
            time.sleep(0.05)

        # capture FPS over ~3s
        n, t0 = 0, time.time()
        w = h = None
        while time.time() - t0 < 3.0:
            frame = src.read()
            if frame is not None:
                n += 1
                if w is None:
                    h, w = frame.shape[:2]
            time.sleep(0.001)
        dt = time.time() - t0
        fps = n / dt if dt else 0
        print(f"capture: {n} frames in {dt:.2f}s -> {fps:.1f} fps "
              f"(frame {w}x{h})  [target >= 25]")

        # input latency: time a few center swipes
        if w and h:
            lat = []
            for _ in range(5):
                s = time.time()
                ctrl.swipe(int(w * 0.5), int(h * 0.6), int(w * 0.3), int(h * 0.6))
                lat.append((time.time() - s) * 1000)
            print(f"swipe latency: avg {sum(lat)/len(lat):.0f} ms, "
                  f"min {min(lat):.0f} ms  [target < 100 ms]")
    finally:
        src.stop()


if __name__ == "__main__":
    main()
