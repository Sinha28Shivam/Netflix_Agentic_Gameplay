"""
src/games/subway_surfers/perception.py — real-time CV for the endless run.

Turns a BGR frame (from src/device/fast_io.py) into a compact ``LaneState`` the
runner policy acts on. Deliberately lightweight (cv2 + numpy, no model) so it
runs at frame cadence.

Approach (rule-based CV):
  * Three LANES (left / center / right). Because the track recedes to a vanishing
    point, each lane is a TRAPEZOID, not a rectangle — defined by calibration.
  * A DANGER ZONE: a near horizontal band where obstacles matter *now*.
  * OBSTACLE per lane: within each lane's slice of the danger zone, measure how
    much of the area is "non-track" (edges + saturated color blobs). High
    coverage => that lane is blocked.
  * PLAYER lane: the lane with the most player-colored pixels in the bottom band.

All thresholds/geometry come from a calibration dict (see DEFAULT_CALIBRATION /
data/calibration.json), so the same code adapts to different resolutions/devices
without edits — only the numbers change.

NOTE: the constants below are STARTING POINTS. Real obstacle/jump/roll
discrimination must be tuned against live frames on the target device (see the
plan's "on-device tuning" phase). The pipeline and its unit tests are exact; the
magic numbers are calibration.
"""

from dataclasses import dataclass, field
from typing import List, Optional


DEFAULT_CALIBRATION = {
    # Fractions of frame height. The playfield we analyse and the near band.
    "field_top": 0.45,        # ignore sky/HUD above this
    "field_bottom": 0.92,     # ignore the very bottom (player/thumb)
    "danger_top": 0.55,       # near band where an obstacle is imminent
    "danger_bottom": 0.80,
    "player_band_top": 0.78,  # where to look for the player to infer current lane
    # Lane x-fractions at the NEAR edge (bottom) — trapezoid widens toward viewer.
    "lane_near_bounds": [0.16, 0.40, 0.60, 0.84],   # 3 lanes -> 4 boundaries
    "lane_far_bounds":  [0.40, 0.46, 0.54, 0.60],   # narrower near vanishing point
    # Detection thresholds.
    "block_coverage": 0.14,   # fraction of danger-lane area that is "obstacle" -> blocked
    "low_obstacle_v": 0.70,   # obstacle centroid low in danger band -> roll-able barrier
    "high_obstacle_v": 0.30,  # obstacle centroid high -> jump-able / overhead
    "edge_canny_lo": 60,
    "edge_canny_hi": 160,
}


@dataclass
class LaneState:
    """Compact perception output for one frame."""
    blocked: List[bool] = field(default_factory=lambda: [False, False, False])  # L,C,R
    player_lane: int = 1                 # 0=left, 1=center, 2=right
    low_obstacle: bool = False           # a roll-able barrier ahead in player lane
    high_obstacle: bool = False          # a jump-able / overhead obstacle ahead
    coins_lane: Optional[int] = None     # lane index richest in coins, if detected
    coverage: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def clear_lanes(self) -> List[int]:
        return [i for i, b in enumerate(self.blocked) if not b]


def _lane_x_bounds(cal, w, v):
    """Interpolate lane boundary x-positions at vertical fraction v in the field
    (0=far/top, 1=near/bottom of the field), giving trapezoidal lanes."""
    near = cal["lane_near_bounds"]
    far = cal["lane_far_bounds"]
    return [int(w * (far[i] + (near[i] - far[i]) * v)) for i in range(len(near))]


def perceive(frame, calibration: Optional[dict] = None) -> LaneState:
    """Analyse a BGR frame -> LaneState. Pure function (no device/IO)."""
    import cv2
    import numpy as np

    cal = {**DEFAULT_CALIBRATION, **(calibration or {})}
    if frame is None or getattr(frame, "size", 0) == 0:
        return LaneState()

    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, cal["edge_canny_lo"], cal["edge_canny_hi"])
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]

    # An "obstacle" pixel = a strong edge OR a saturated (colorful) region — both
    # stand out against the muted grey track. Combined into a 0/1 mask.
    obstacle_mask = ((edges > 0) | (sat > 90)).astype(np.uint8)

    dtop = int(h * cal["danger_top"])
    dbot = int(h * cal["danger_bottom"])
    field_top = h * cal["field_top"]
    field_bot = h * cal["field_bottom"]
    # vertical fraction (0..1) of the danger band's mid-line within the field
    v_mid = ((dtop + dbot) / 2 - field_top) / max(1.0, (field_bot - field_top))
    bounds = _lane_x_bounds(cal, w, max(0.0, min(1.0, v_mid)))

    coverage, blocked, centroids = [], [], []
    for i in range(3):
        x0, x1 = bounds[i], bounds[i + 1]
        cell = obstacle_mask[dtop:dbot, x0:x1]
        area = cell.size or 1
        cov = float(cell.sum()) / area
        coverage.append(cov)
        blocked.append(cov >= cal["block_coverage"])
        # vertical centroid of obstacle pixels within the danger band (0=top,1=bot)
        ys = np.where(cell.sum(axis=1) > 0)[0]
        centroids.append((ys.mean() / max(1, cell.shape[0])) if ys.size else None)

    # Player lane = most player-ish pixels low on screen. Without a trained
    # detector we approximate by the fullest lane in the player band; a game
    # profile can override with a color/template match on the character.
    pband = obstacle_mask[int(h * cal["player_band_top"]):int(field_bot), :]
    pbounds = _lane_x_bounds(cal, w, 1.0)
    p_counts = [int(pband[:, pbounds[i]:pbounds[i + 1]].sum()) for i in range(3)]
    player_lane = int(max(range(3), key=lambda i: p_counts[i])) if any(p_counts) else 1

    # Roll vs jump hint from the obstacle centroid in the PLAYER's lane.
    low_ob = high_ob = False
    c = centroids[player_lane]
    if blocked[player_lane] and c is not None:
        if c >= cal["low_obstacle_v"]:
            low_ob = True          # obstacle sits low -> a barrier to roll under
        elif c <= cal["high_obstacle_v"]:
            high_ob = True         # obstacle sits high/overhead -> jump

    return LaneState(
        blocked=blocked,
        player_lane=player_lane,
        low_obstacle=low_ob,
        high_obstacle=high_ob,
        coverage=coverage,
    )
