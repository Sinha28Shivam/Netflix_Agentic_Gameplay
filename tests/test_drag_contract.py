"""
test_drag_contract.py — characterization test locking the Bloons drag-and-drop
gesture so the plugin refactor cannot silently change tap/drag behavior.

It asserts (a) the drag() default gesture parameters and (b) the exact
motionevent sequence emitted (DOWN -> stepped MOVEs -> UP). Device-free: the
adb call and time.sleep are stubbed. Run with:

    python -m pytest tests/test_drag_contract.py -v
"""

import inspect
import unittest
from unittest import mock

from src.device.android import adb_utils


class TestDragContract(unittest.TestCase):
    def test_drag_default_parameters_unchanged(self):
        """The press-hold-carry-release tuning Bloons placement depends on."""
        sig = inspect.signature(adb_utils.drag)
        defaults = {n: p.default for n, p in sig.parameters.items()
                    if p.default is not inspect.Parameter.empty}
        self.assertEqual(defaults["duration_ms"], 700)
        self.assertEqual(defaults["hold"], True)
        self.assertEqual(defaults["steps"], 12)
        self.assertEqual(defaults["hold_ms"], 450)
        self.assertEqual(defaults["settle_ms"], 1200)

    def test_drag_emits_down_steps_up(self):
        calls = []

        with mock.patch.object(adb_utils, "_adb", side_effect=lambda c: calls.append(c)), \
             mock.patch.object(adb_utils, "_MOTIONEVENT_SUPPORTED", True), \
             mock.patch("time.sleep", lambda *_a, **_k: None):
            adb_utils.drag(100, 200, 300, 400)

        # First event grabs at the source, last releases at the target.
        self.assertEqual(calls[0], "shell input motionevent DOWN 100 200")
        self.assertEqual(calls[-1], "shell input motionevent UP 300 400")

        moves = [c for c in calls if "MOVE" in c]
        self.assertEqual(len(moves), 12)                       # default steps
        self.assertEqual(moves[-1], "shell input motionevent MOVE 300 400")

    def test_drag_falls_back_to_swipe_without_motionevent(self):
        calls = []
        with mock.patch.object(adb_utils, "_adb", side_effect=lambda c: calls.append(c)), \
             mock.patch.object(adb_utils, "_MOTIONEVENT_SUPPORTED", False), \
             mock.patch("time.sleep", lambda *_a, **_k: None):
            adb_utils.drag(100, 200, 300, 400, hold=False)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("shell input swipe 100 200 300 400"))


class TestDeviceSessionDragContract(unittest.TestCase):
    """The two-device DeviceSession must reproduce the same drag gesture."""

    def test_session_drag_matches_single_device_sequence(self):
        from src.device.session import DeviceSession

        sess = DeviceSession("emulator-5554")
        sess._motionevent = True  # skip the capability probe
        calls = []
        with mock.patch.object(sess, "run", side_effect=lambda args, **k: calls.append(args)), \
             mock.patch("time.sleep", lambda *_a, **_k: None):
            sess.drag(100, 200, 300, 400)

        events = [c[3:] for c in calls if len(c) >= 3 and c[2] == "motionevent"]
        kinds = [c[3] for c in calls if len(c) >= 4 and c[2] == "motionevent"]
        self.assertEqual(kinds[0], "DOWN")
        self.assertEqual(kinds[-1], "UP")
        self.assertEqual(kinds.count("MOVE"), 12)
        # every event carries the target serial
        self.assertTrue(all(c[0:2] == ["shell", "input"] for c in calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
