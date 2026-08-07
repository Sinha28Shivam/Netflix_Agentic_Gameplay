"""
Unit tests for RunnerMixin: the pure dodge policy (decide) on synthetic
LaneStates, and the control loop against a fake FrameSource/FastControl. No
device, no cv2 needed for the policy tests.

    python -m pytest tests/test_runner_genre.py -v
"""

import unittest

import numpy as np

from src.device.fast_io import FrameSource, FastControl
from src.games.genres.runner import RunnerMixin
from src.games.subway_surfers.perception import LaneState


class _Policy(RunnerMixin):
    def perceive(self, frame):  # not used by decide tests
        return LaneState()


P = _Policy()


class TestDecide(unittest.TestCase):
    def test_clear_lane_no_action(self):
        self.assertIsNone(P.decide(LaneState(blocked=[False, False, False], player_lane=1)))

    def test_low_barrier_rolls(self):
        s = LaneState(blocked=[False, True, False], player_lane=1, low_obstacle=True)
        self.assertEqual(P.decide(s), "roll")

    def test_high_obstacle_jumps(self):
        s = LaneState(blocked=[False, True, False], player_lane=1, high_obstacle=True)
        self.assertEqual(P.decide(s), "jump")

    def test_blocked_center_switches_to_clear_lane(self):
        # center blocked, no roll/jump hint; left clear, right clear -> nearest (left, tie->lower)
        s = LaneState(blocked=[False, True, False], player_lane=1)
        self.assertIn(P.decide(s), ("left", "right"))

    def test_blocked_switch_prefers_only_clear_side(self):
        s = LaneState(blocked=[True, True, False], player_lane=1)
        self.assertEqual(P.decide(s), "right")

    def test_boxed_in_jumps(self):
        s = LaneState(blocked=[True, True, True], player_lane=1)
        self.assertEqual(P.decide(s), "jump")

    def test_drifts_toward_coins_when_clear(self):
        s = LaneState(blocked=[False, False, False], player_lane=1, coins_lane=2)
        self.assertEqual(P.decide(s), "right")

    def test_does_not_chase_coins_into_blocked_lane(self):
        s = LaneState(blocked=[False, False, True], player_lane=1, coins_lane=2)
        self.assertIsNone(P.decide(s))


class _FakeControl(FastControl):
    def __init__(self):
        self.swipes = []

    def swipe(self, x1, y1, x2, y2, duration_ms=80):
        self.swipes.append((x1, y1, x2, y2))

    def tap(self, x, y):
        pass


class _SeqSource(FrameSource):
    """Yields changing frames (so stall detection doesn't fire)."""
    def __init__(self):
        self.i = 0

    def start(self):
        pass

    def read(self):
        self.i += 1
        return np.full((160, 90, 3), (self.i * 9) % 255, dtype=np.uint8)

    def stop(self):
        pass


class _ScriptedRunner(RunnerMixin):
    tick_hz = 200
    stale_seconds = 999  # disable stall for this test

    def __init__(self, states):
        self._states = states
        self._k = 0

    def perceive(self, frame):
        s = self._states[min(self._k, len(self._states) - 1)]
        self._k += 1
        return s

    def run_ended(self, state, frame):
        return self._k >= len(self._states)


class TestControlLoop(unittest.TestCase):
    def test_loop_dispatches_actions_and_ends(self):
        states = [
            LaneState(blocked=[False, True, False], player_lane=1, low_obstacle=True),  # roll
            LaneState(blocked=[True, True, False], player_lane=1),                      # right
            LaneState(blocked=[False, False, False], player_lane=1),                    # none
        ]
        r = _ScriptedRunner(states)
        ctrl = _FakeControl()
        stats = r.run_until_crash(_SeqSource(), ctrl, max_seconds=5)
        self.assertEqual(stats["ended_reason"], "run_ended")
        self.assertEqual(stats["actions"]["roll"], 1)
        self.assertEqual(stats["actions"]["right"], 1)
        self.assertGreaterEqual(len(ctrl.swipes), 2)

    def test_stall_detection_ends_run(self):
        class _StaticSource(FrameSource):
            def start(self): pass
            def read(self): return np.zeros((160, 90, 3), dtype=np.uint8)
            def stop(self): pass

        class _Idle(RunnerMixin):
            tick_hz = 200
            stale_seconds = 0.05
            def perceive(self, frame): return LaneState()

        stats = _Idle().run_until_crash(_StaticSource(), _FakeControl(), max_seconds=5)
        self.assertEqual(stats["ended_reason"], "stalled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
