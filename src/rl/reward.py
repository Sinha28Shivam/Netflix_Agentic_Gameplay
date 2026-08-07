"""
src/rl/reward.py — the reward functions, in one place.

This is the single source of truth for the reward tables documented in
REINFORCEMENT_LEARNING.md §3. Two reward regimes:

  NavigationReward — sparse goal reward + per-step cost for the *menu
      navigation* MDP. This is what NavigationMDP bakes into its P table and
      what QANavEnv / LiveDeviceEnv use for the navigation phase.

  GameplayReward   — dense reward for *in-match* play, assembled from the
      signals the pipeline already produces: OracleAgent's victory/defeat
      verdict, cash/round deltas from read_hud, a stuck-screen penalty, and
      performance-threshold penalties from perf_utils. Used by LiveDeviceEnv
      for the (roadmap Phase 2) combat policy.

Everything reads from src.core.config so tuning lives with the rest of the
pipeline's constants. Device/LLM helpers are imported lazily so this module is
safe to import in a pure-offline (no-adb, no-numpy) context.
"""

from dataclasses import dataclass

from src.rl.mdp import DEFAULT_GOAL_REWARD, DEFAULT_STEP_COST


@dataclass
class NavigationReward:
    """Sparse navigation reward: reach the goal screen in as few taps as possible.

    reward(s, a, s') =
        +goal_reward   if s' is the goal screen   (terminal)
        -step_cost     on every transition        (shortest-path pressure)
    """

    goal_reward: float = DEFAULT_GOAL_REWARD
    step_cost: float = DEFAULT_STEP_COST

    def __call__(self, reached_goal: bool) -> float:
        return (self.goal_reward if reached_goal else 0.0) - self.step_cost


class GameplayReward:
    """Dense in-match reward assembled from existing pipeline signals.

    Component            Source                              Sign / shaping
    -------------------  ----------------------------------  ------------------------------
    victory              OracleAgent.verify -> PASS          +GOAL   (terminal)
    defeat               OracleAgent.verify -> FAIL          -GOAL   (terminal)
    round advanced       read_hud round delta (r1 > r0)      +round_bonus * Δround
    tower placed         read_hud cash delta  (cash < prev)  +place_bonus (verified spend)
    screen made progress screen_signature changed            +tiny_progress
    stuck (no change)    memory.same_scene_count             -stuck_penalty past threshold
    low fps              perf < MIN_ACCEPTABLE_FPS           -perf_penalty
    over memory budget   perf > MAX_ACCEPTABLE_MEMORY_MB     -perf_penalty
    per-step time cost   every step                          -step_cost
    """

    def __init__(self):
        import src.core.config as config
        self.goal = 1.0
        self.round_bonus = 0.20
        self.place_bonus = 0.05
        self.tiny_progress = 0.01
        self.stuck_penalty = 0.10
        self.perf_penalty = 0.10
        self.step_cost = DEFAULT_STEP_COST
        self.min_fps = config.MIN_ACCEPTABLE_FPS
        self.max_mem_mb = config.MAX_ACCEPTABLE_MEMORY_MB
        self.stuck_threshold = config.SAME_SCENE_RECOVERY_THRESHOLD

    def __call__(self, prev, curr, oracle_verdict, perf_sample=None, same_scene_count=0):
        """Compute the scalar reward for one in-match step.

        prev, curr:  dicts with optional 'cash' and 'round' (from read_hud)
        oracle_verdict: dict from OracleAgent.verify, e.g. {"status": "PASS"|"FAIL"|"RUNNING"}
        perf_sample: optional dict with 'fps' / 'memory_mb'
        same_scene_count: consecutive no-progress steps (memory.same_scene_count)
        Returns (reward, done).
        """
        status = (oracle_verdict or {}).get("status", "RUNNING")
        if status == "PASS":
            return self.goal - self.step_cost, True
        if status == "FAIL":
            return -self.goal - self.step_cost, True

        reward = -self.step_cost
        r0, r1 = _num(prev.get("round")), _num(curr.get("round"))
        if r0 is not None and r1 is not None and r1 > r0:
            reward += self.round_bonus * (r1 - r0)

        c0, c1 = _num(prev.get("cash")), _num(curr.get("cash"))
        if c0 is not None and c1 is not None and c1 < c0:
            reward += self.place_bonus  # a spend => a tower/upgrade actually happened

        if same_scene_count >= self.stuck_threshold:
            reward -= self.stuck_penalty

        if perf_sample:
            fps = _num(perf_sample.get("fps"))
            mem = _num(perf_sample.get("memory_mb"))
            if fps is not None and fps < self.min_fps:
                reward -= self.perf_penalty
            if mem is not None and mem > self.max_mem_mb:
                reward -= self.perf_penalty

        return reward, False


def _num(v):
    """Best-effort numeric coercion — HUD OCR sometimes yields strings/None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
