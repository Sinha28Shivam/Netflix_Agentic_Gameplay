"""
src/rl/env.py — environments the policy trains and runs against.

QANavEnv:     a minimal Gymnasium-compatible environment (reset/step) that wraps
              NavigationMDP. Fully offline and deterministic given a seed, so it
              trains in milliseconds with no device, no LLM, and no API cost.
              (We implement the Gymnasium API by hand rather than depend on the
              `gymnasium` package, which is not installed — see requirements.txt.)

LiveDeviceEnv: the SAME step/reset contract, but backed by the real pipeline —
              VisionAgent for observation, ExecutorAgent for actions, OracleAgent
              + read_hud for reward, force_stop/launch_game for reset. This is how
              a policy trained offline is evaluated (and, later, fine-tuned) on a
              physical device. Device/LLM imports are lazy so importing this
              module never requires adb or an API key.
"""

import random
from typing import Optional

from src.rl.mdp import NavigationMDP


class QANavEnv:
    """Offline navigation environment over a NavigationMDP.

    Gymnasium-style contract:
        obs = env.reset(seed=...)                     -> state index (int)
        obs, reward, terminated, truncated, info = env.step(action_index)
    """

    def __init__(self, mdp: NavigationMDP, max_steps: int = 50, seed: Optional[int] = None):
        self.mdp = mdp
        self.max_steps = max_steps
        self.n_states = len(mdp.states)
        self.n_actions = len(mdp.actions)
        self._rng = random.Random(seed)
        self._s = mdp.reset_index()
        self._steps = 0

    def reset(self, seed: Optional[int] = None):
        if seed is not None:
            self._rng.seed(seed)
        self._s = self.mdp.reset_index()
        self._steps = 0
        return self._s

    def step(self, action_index: int):
        ns, reward, done = self.mdp.step_index(self._s, action_index, self._rng)
        self._s = ns
        self._steps += 1
        truncated = self._steps >= self.max_steps and not done
        info = {
            "state_label": self.mdp.states[ns],
            "action": self.mdp.actions[action_index],
        }
        return ns, reward, done, truncated, info

    # Convenience for debugging / value-iteration rollouts.
    @property
    def state(self) -> int:
        return self._s


class LiveDeviceEnv:
    """On-device environment: the offline-trained policy, evaluated for real.

    Composes existing pipeline components ONLY (no new device code):
        observation : VisionAgent.observe(screenshot_b64, ui_texts) -> state dict
        state key   : the observed `scene`/label -> NavigationMDP state index
        action      : NavigationMDP action -> DecisionAgent JSON -> ExecutorAgent.execute
        reward      : NavigationReward on reaching the goal scene
        reset       : force_stop + launch_game

    Intended for evaluation and (roadmap) online fine-tuning. Kept import-light:
    all adb/LLM imports happen inside methods.
    """

    def __init__(self, mdp: NavigationMDP, client=None, max_steps: int = 40):
        self.mdp = mdp
        self.client = client
        self.max_steps = max_steps
        self._steps = 0
        self._executor = None
        self._vision = None

    def _lazy_init(self):
        if self._executor is None:
            from src.agents.execution.executor_agent import ExecutorAgent
            self._executor = ExecutorAgent()
        if self._vision is None and self.client is not None:
            from src.agents.core.vision_agent import VisionAgent
            self._vision = VisionAgent(self.client)

    def _observe_state_index(self):
        """Capture a screenshot, run the VisionAgent, map its scene to a state."""
        from src.device.device import get_screenshot_base64, get_ui_texts
        b64 = get_screenshot_base64()
        ui_texts = get_ui_texts()
        obs = self._vision.observe(b64, ui_texts) if self._vision else {}
        scene = obs.get("scene", "unknown")
        idx = self.mdp.state_index(scene)
        return idx, obs

    def reset(self, seed: Optional[int] = None):
        from src.device.device import force_stop, launch_game
        self._lazy_init()
        force_stop()
        launch_game()
        self._steps = 0
        idx, _ = self._observe_state_index()
        return idx

    def step(self, action_index: int):
        self._lazy_init()
        decision = self.mdp.action_to_decision(action_index, why="RL optimal policy (on-device)")
        # ExecutorAgent needs the live state's actionable_elements to resolve the tap.
        _, obs = self._observe_state_index()
        self._executor.execute(decision, obs)
        self._steps += 1

        ns, obs2 = self._observe_state_index()
        reached_goal = ns is not None and self.mdp.is_goal(ns)
        from src.rl.reward import NavigationReward
        reward = NavigationReward(self.mdp.goal_reward, self.mdp.step_cost)(reached_goal)
        truncated = self._steps >= self.max_steps and not reached_goal
        info = {"scene": obs2.get("scene", "unknown"), "decision": decision}
        return ns, reward, reached_goal, truncated, info
