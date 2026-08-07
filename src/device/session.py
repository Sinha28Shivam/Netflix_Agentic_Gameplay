"""
src/device/session.py — DeviceSession: a per-serial handle for driving ONE
specific device.

WHY THIS EXISTS
The default device layer (device.py / adb_utils.py) targets a single device via
the global ``config.DEVICE_SERIAL``. That is exactly right for single-player and
for automating ONE client of a multiplayer game. True two-device / two-client
multiplayer (two synchronized players) needs each driver bound to a DIFFERENT
serial at the same time — which a single global can't express.

DeviceSession is that extension point. Each instance carries its own serial and
exposes the same primitive surface (tap/swipe/drag/screencap/force_stop/
launch_game) targeting that device. The global single-device functions are
UNCHANGED, so the default path — and Bloons — behave exactly as before; this is
purely additive.

Status: foundation. A multiplayer game that wants two clients constructs two
sessions (``DeviceSession(serial_a)``, ``DeviceSession(serial_b)``) and drives
them. Wiring a game's play-loop to accept N sessions is left to that game; the
single-device engine path does not use this module.

Example:
    from src.device.session import DeviceSession, list_devices
    a, b = [DeviceSession(s) for s in list_devices()[:2]]
    a.launch_game("com.example.pvp"); b.launch_game("com.example.pvp")
    a.tap(500, 1600); b.tap(500, 1600)
"""

import subprocess
import time

import src.core.config as config

# Drag gesture defaults — kept identical to adb_utils.drag() so a two-device
# game gets the same press-hold-carry-release placement behavior.
_DRAG_HOLD_MS = 450
_DRAG_STEPS = 12
_DRAG_SETTLE_MS = 1200


def list_devices():
    """Return the serials of all attached devices (adb devices)."""
    out = subprocess.run([config.ADB_PATH, "devices"], capture_output=True)
    serials = []
    for line in out.stdout.decode("utf-8", errors="ignore").splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


class DeviceSession:
    """Primitive device I/O bound to one explicit serial."""

    def __init__(self, serial: str):
        if not serial:
            raise ValueError("DeviceSession requires an explicit device serial.")
        self.serial = serial
        self._motionevent = None  # cached capability probe

    # ---- core callers -----------------------------------------------------
    def run(self, args, timeout: int = 15) -> str:
        cmd = [config.ADB_PATH, "-s", self.serial] + args
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout)
            return r.stdout.decode("utf-8", errors="ignore")
        except subprocess.TimeoutExpired:
            print(f"⚠ adb timed out on {self.serial}: {' '.join(map(str, args))}")
            return ""

    def _shell(self, cmd: str):
        self.run(["shell"] + cmd.split())

    # ---- app lifecycle ----------------------------------------------------
    def force_stop(self, pkg: str):
        self.run(["shell", "am", "force-stop", pkg])
        time.sleep(1)

    def launch_game(self, pkg: str, activity: str = ""):
        if activity:
            self.run(["shell", "am", "start", "-n", f"{pkg}/{activity}"])
        else:
            self.run(["shell", "monkey", "-p", pkg, "1"])
        time.sleep(5)

    # ---- perception -------------------------------------------------------
    def screencap(self, local_path: str):
        # exec-out returns raw PNG bytes, so capture bytes directly (not decoded).
        raw = subprocess.run(
            [config.ADB_PATH, "-s", self.serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=30,
        ).stdout
        with open(local_path, "wb") as fh:
            fh.write(raw)
        return local_path

    # ---- input ------------------------------------------------------------
    def tap(self, x: int, y: int):
        self.run(["shell", "input", "tap", str(int(x)), str(int(y))])

    def swipe(self, x1, y1, x2, y2, duration_ms: int = 350):
        self.run(["shell", "input", "swipe", str(int(x1)), str(int(y1)),
                  str(int(x2)), str(int(y2)), str(int(duration_ms))])
        time.sleep(1.0)

    def _supports_motionevent(self) -> bool:
        if self._motionevent is None:
            sdk = self.run(["shell", "getprop", "ro.build.version.sdk"]).strip()
            try:
                self._motionevent = bool(sdk) and int(sdk) >= 26
            except ValueError:
                self._motionevent = False
        return self._motionevent

    def drag(self, x1, y1, x2, y2, hold: bool = True):
        """Press-hold-carry-release drag — same gesture as adb_utils.drag()."""
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        if hold and self._supports_motionevent():
            self.run(["shell", "input", "motionevent", "DOWN", str(x1), str(y1)])
            time.sleep(_DRAG_HOLD_MS / 1000.0)
            for i in range(1, _DRAG_STEPS + 1):
                xi = x1 + (x2 - x1) * i // _DRAG_STEPS
                yi = y1 + (y2 - y1) * i // _DRAG_STEPS
                self.run(["shell", "input", "motionevent", "MOVE", str(xi), str(yi)])
                time.sleep(0.03)
            time.sleep(0.15)
            self.run(["shell", "input", "motionevent", "UP", str(x2), str(y2)])
        else:
            self.swipe(x1, y1, x2, y2, duration_ms=700)
        time.sleep(_DRAG_SETTLE_MS / 1000.0)
