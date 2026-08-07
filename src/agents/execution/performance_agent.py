import time

from src.core.config import (
    GAME_PACKAGE,
    MAX_ACCEPTABLE_LOAD_SECONDS,
    MAX_ACCEPTABLE_MEMORY_MB,
    MIN_ACCEPTABLE_FPS,
)
from src.device.perf_utils import get_cpu_percent, get_fps_stats, get_memory_mb


class PerformanceAgent:
    def __init__(self, package=GAME_PACKAGE):
        self.package = package
        self.samples = []
        self.load_times = []
        self._load_start = None
        self._load_start_scene = None

    def sample(self, scene):
        fps_stats = get_fps_stats(self.package)
        sample = {
            "scene": scene,
            "fps": fps_stats["fps"],
            "janky_frames": fps_stats["janky_frames"],
            "memory_mb": get_memory_mb(self.package),
            "cpu_pct": get_cpu_percent(self.package),
            "timestamp": time.time(),
        }
        self.samples.append(sample)
        return sample

    def mark_load_start(self, from_scene):
        self._load_start = time.time()
        self._load_start_scene = from_scene

    def mark_load_end(self, to_scene):
        if self._load_start is None:
            return None
        elapsed = time.time() - self._load_start
        self.load_times.append(
            {"from": self._load_start_scene, "to": to_scene, "seconds": round(elapsed, 2)}
        )
        self._load_start = None
        return elapsed

    def summary(self):
        fps_values = [s["fps"] for s in self.samples if s["fps"]]
        mem_values = [s["memory_mb"] for s in self.samples if s["memory_mb"]]

        avg_fps = round(sum(fps_values) / len(fps_values), 1) if fps_values else None
        max_mem = max(mem_values) if mem_values else None
        slow_loads = [lt for lt in self.load_times if lt["seconds"] > MAX_ACCEPTABLE_LOAD_SECONDS]

        issues = []
        if avg_fps is not None and avg_fps < MIN_ACCEPTABLE_FPS:
            issues.append(f"Average FPS {avg_fps} below threshold {MIN_ACCEPTABLE_FPS}")
        if max_mem is not None and max_mem > MAX_ACCEPTABLE_MEMORY_MB:
            issues.append(f"Peak memory {max_mem}MB above threshold {MAX_ACCEPTABLE_MEMORY_MB}MB")
        if slow_loads:
            issues.append(
                f"{len(slow_loads)} scene transition(s) exceeded {MAX_ACCEPTABLE_LOAD_SECONDS}s"
            )

        return {
            "status": "FAIL" if issues else "PASS",
            "avg_fps": avg_fps,
            "peak_memory_mb": max_mem,
            "load_times": self.load_times,
            "issues": issues,
            "samples": self.samples,
        }
