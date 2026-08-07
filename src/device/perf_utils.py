from src.device.android.adb_utils import run_adb, _active_pkg

NS_PER_FRAME_60FPS = 16_666_666  # ns budget for a 60fps frame


def get_fps_stats(package=None):
    package = package or _active_pkg()
    """
    Parse `dumpsys gfxinfo <pkg> framestats` to estimate FPS and jank.
    Field layout can vary slightly across Android versions — treat this as
    a heuristic, not a certified frame-timing tool.
    Returns {"fps": float|None, "janky_frames": int, "total_frames": int}.
    """
    output = run_adb(["shell", "dumpsys", "gfxinfo", package, "framestats"])

    frame_times = []
    for line in output.splitlines():
        parts = line.strip().split(",")
        if len(parts) > 13 and parts[0].isdigit():
            try:
                frame_times.append(int(parts[1]))  # VSYNC timestamp column
            except ValueError:
                continue

    if len(frame_times) < 2:
        return {"fps": None, "janky_frames": 0, "total_frames": 0}

    frame_times.sort()
    deltas = [b - a for a, b in zip(frame_times, frame_times[1:]) if b > a]
    if not deltas:
        return {"fps": None, "janky_frames": 0, "total_frames": 0}

    avg_delta_ns = sum(deltas) / len(deltas)
    fps = 1e9 / avg_delta_ns if avg_delta_ns > 0 else None
    janky = sum(1 for d in deltas if d > NS_PER_FRAME_60FPS * 1.5)

    return {
        "fps": round(fps, 1) if fps else None,
        "janky_frames": janky,
        "total_frames": len(deltas),
    }


def get_memory_mb(package=None):
    """Parse `dumpsys meminfo <pkg>` for total PSS in MB."""
    package = package or _active_pkg()
    output = run_adb(["shell", "dumpsys", "meminfo", package])
    for line in output.splitlines():
        if "TOTAL" in line:
            digits = "".join(ch for ch in line.split("TOTAL")[-1] if ch.isdigit() or ch == " ")
            tokens = digits.split()
            if tokens:
                try:
                    return round(int(tokens[0]) / 1024, 1)
                except ValueError:
                    continue
    return None


def get_cpu_percent(package=None):
    """Parse `top -n 1 -b` for the game process's CPU%."""
    package = package or _active_pkg()
    output = run_adb(["shell", "top", "-n", "1", "-b"])
    for line in output.splitlines():
        if package in line:
            for part in line.split():
                if part.endswith("%"):
                    try:
                        return float(part.rstrip("%"))
                    except ValueError:
                        continue
    return None
