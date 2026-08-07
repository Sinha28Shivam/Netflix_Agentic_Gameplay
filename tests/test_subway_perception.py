"""
Offline unit tests for the Subway Surfers CV perception. Uses SYNTHETIC frames
(grey 'track' + a saturated block standing in for an obstacle) so the pipeline
logic is verified without real game frames or a device. Real thresholds still
need on-device calibration; these lock the pipeline's behavior.

    python -m pytest tests/test_subway_perception.py -v
"""

import unittest

import numpy as np

from src.games.subway_surfers.perception import perceive, DEFAULT_CALIBRATION, LaneState

H, W = 1920, 1080
CAL = DEFAULT_CALIBRATION


def _blank():
    # Uniform grey 'track': zero saturation, no edges -> no obstacles.
    return np.full((H, W, 3), 128, dtype=np.uint8)


def _lane_x(i):
    # Match perception's near-edge lane bounds well enough to target a lane.
    near = CAL["lane_near_bounds"]
    return int(W * near[i]), int(W * near[i + 1])


def _fill_obstacle(frame, lane, y0_frac, y1_frac):
    x0, x1 = _lane_x(lane)
    # nudge inward so the block lands inside the trapezoid at the danger band
    x0 += 30
    x1 -= 30
    y0, y1 = int(H * y0_frac), int(H * y1_frac)
    frame[y0:y1, x0:x1] = (0, 0, 255)  # saturated red -> high HSV saturation
    return frame


class TestPerception(unittest.TestCase):
    def test_blank_frame_has_no_blocked_lanes(self):
        st = perceive(_blank())
        self.assertIsInstance(st, LaneState)
        self.assertEqual(st.blocked, [False, False, False])

    def test_none_frame_is_safe(self):
        st = perceive(None)
        self.assertEqual(st.blocked, [False, False, False])

    def test_center_obstacle_blocks_center(self):
        f = _fill_obstacle(_blank(), lane=1, y0_frac=0.56, y1_frac=0.79)
        st = perceive(f)
        self.assertTrue(st.blocked[1], f"center should be blocked, coverage={st.coverage}")
        self.assertFalse(st.blocked[0])
        self.assertFalse(st.blocked[2])

    def test_left_obstacle_blocks_left(self):
        f = _fill_obstacle(_blank(), lane=0, y0_frac=0.56, y1_frac=0.79)
        st = perceive(f)
        self.assertTrue(st.blocked[0], f"left should be blocked, coverage={st.coverage}")

    def test_low_barrier_sets_low_obstacle(self):
        # obstacle sitting LOW in the danger band, in the (default) center player lane
        f = _fill_obstacle(_blank(), lane=1, y0_frac=0.74, y1_frac=0.80)
        st = perceive(f)
        self.assertEqual(st.player_lane, 1)
        self.assertTrue(st.blocked[1])
        self.assertTrue(st.low_obstacle)
        self.assertFalse(st.high_obstacle)

    def test_high_obstacle_sets_jump(self):
        f = _fill_obstacle(_blank(), lane=1, y0_frac=0.55, y1_frac=0.60)
        st = perceive(f)
        self.assertTrue(st.blocked[1])
        self.assertTrue(st.high_obstacle)
        self.assertFalse(st.low_obstacle)

    def test_clear_lanes_helper(self):
        f = _fill_obstacle(_blank(), lane=1, y0_frac=0.56, y1_frac=0.79)
        st = perceive(f)
        self.assertEqual(set(st.clear_lanes()), {0, 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
