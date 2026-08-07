"""
src/rl/qlearning.py — the learning algorithms.

QLearningAgent — tabular Q-learning (off-policy TD control) with an
    epsilon-greedy behaviour policy and an exponential exploration schedule.
    The Q-table is a plain 2-D list (states x actions), so the agent runs with
    ZERO third-party dependencies. numpy is used only if available, purely as a
    speed-up — the results are identical either way.

value_iteration — an exact model-based baseline. Because NavigationMDP exposes
    the full transition/reward model (P), we can compute the optimal value
    function directly. This is used in tests as ground truth: a correctly
    trained Q-learning policy must match the value-iteration optimum (zero
    regret) on this small MDP.

Both operate on integer state/action indices from NavigationMDP, and both
produce a greedy policy (state_index -> action_index) that RLDecisionAgent
turns into on-device taps.
"""

import json
import random
from typing import Dict, List, Optional

from src.rl.mdp import NavigationMDP


# ============================================================ Q-LEARNING
class QLearningAgent:
    """Tabular Q-learning.

    Update rule (per step):
        Q[s,a] <- Q[s,a] + alpha * (r + gamma * max_a' Q[s',a'] - Q[s,a])
    """

    def __init__(
        self,
        n_states: int,
        n_actions: int,
        alpha: float = 0.5,
        gamma: float = 0.95,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.02,
        epsilon_decay: float = 0.995,
        seed: Optional[int] = 0,
    ):
        self.n_states = n_states
        self.n_actions = n_actions
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self._rng = random.Random(seed)
        self.Q: List[List[float]] = [[0.0] * n_actions for _ in range(n_states)]
        # Bookkeeping for convergence reporting.
        self.episode_returns: List[float] = []

    # -- action selection --
    def act(self, state: int, greedy: bool = False) -> int:
        if not greedy and self._rng.random() < self.epsilon:
            return self._rng.randrange(self.n_actions)
        return self._argmax(self.Q[state])

    def _argmax(self, row: List[float]) -> int:
        best = max(row)
        # Break ties randomly so the policy doesn't bias toward low indices.
        best_actions = [i for i, v in enumerate(row) if v == best]
        return self._rng.choice(best_actions)

    # -- training --
    def train(self, env, episodes: int = 5000) -> Dict:
        """Run `episodes` of Q-learning against a QANavEnv-style env.
        Returns a summary dict with convergence stats."""
        successes = 0
        for _ in range(episodes):
            state = env.reset()
            done = truncated = False
            ep_return = 0.0
            while not (done or truncated):
                action = self.act(state)
                next_state, reward, done, truncated, _ = env.step(action)
                best_next = max(self.Q[next_state]) if not done else 0.0
                td_target = reward + self.gamma * best_next
                self.Q[state][action] += self.alpha * (td_target - self.Q[state][action])
                state = next_state
                ep_return += reward
            successes += int(done)
            self.episode_returns.append(ep_return)
            self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        return {
            "episodes": episodes,
            "success_rate": successes / episodes if episodes else 0.0,
            "final_epsilon": self.epsilon,
            "mean_return_last_100": _mean(self.episode_returns[-100:]),
        }

    # -- greedy policy extraction --
    def policy(self) -> Dict[int, int]:
        return {s: self._argmax(self.Q[s]) for s in range(self.n_states)}

    def greedy_action(self, state: int) -> int:
        return self._argmax(self.Q[state])

    # -- persistence (JSON, portable, human-inspectable) --
    def save(self, path: str, mdp: Optional[NavigationMDP] = None):
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "n_states": self.n_states,
            "n_actions": self.n_actions,
            "gamma": self.gamma,
            "Q": self.Q,
        }
        if mdp is not None:
            payload["states"] = mdp.states
            payload["actions"] = mdp.actions
            payload["start_state"] = mdp.start_state
            payload["goal_state"] = mdp.goal_state
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "QLearningAgent":
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        agent = cls(payload["n_states"], payload["n_actions"], gamma=payload.get("gamma", 0.95))
        agent.Q = payload["Q"]
        agent.epsilon = 0.0  # loaded policies are exploited, not explored
        agent.meta = {k: payload[k] for k in ("states", "actions", "start_state", "goal_state") if k in payload}
        return agent


# ============================================================ VALUE ITERATION
def value_iteration(mdp: NavigationMDP, gamma: float = 0.95, theta: float = 1e-9,
                    max_iters: int = 10000):
    """Exact optimal value function + greedy policy via the Bellman optimality
    backup over mdp.P. Ground-truth baseline for tests.

    Returns (V, policy) where V is a list[float] over states and policy is a
    dict state_index -> action_index.
    """
    n_states = len(mdp.states)
    n_actions = len(mdp.actions)
    V = [0.0] * n_states
    for _ in range(max_iters):
        delta = 0.0
        for s in range(n_states):
            if mdp.is_goal(s):
                continue  # absorbing terminal — value stays 0
            best = float("-inf")
            for a in range(n_actions):
                q = sum(p * (r + (0.0 if done else gamma * V[ns]))
                        for (p, ns, r, done) in mdp.P[(s, a)])
                if q > best:
                    best = q
            delta = max(delta, abs(best - V[s]))
            V[s] = best
        if delta < theta:
            break

    policy = {}
    for s in range(n_states):
        if mdp.is_goal(s):
            policy[s] = 0
            continue
        best_a, best_q = 0, float("-inf")
        for a in range(n_actions):
            q = sum(p * (r + (0.0 if done else gamma * V[ns]))
                    for (p, ns, r, done) in mdp.P[(s, a)])
            if q > best_q:
                best_q, best_a = q, a
        policy[s] = best_a
    return V, policy


# ============================================================ helpers
def expected_steps_to_goal(mdp: NavigationMDP, policy: Dict[int, int],
                           max_rollouts: int = 2000, seed: int = 0) -> float:
    """Monte-Carlo estimate of the mean number of taps a policy needs to reach
    the goal from the start state — the metric the MD calls 'path length'."""
    rng = random.Random(seed)
    total, reached = 0, 0
    for _ in range(max_rollouts):
        s = mdp.reset_index()
        for step in range(1, 200):
            s, _, done = mdp.step_index(s, policy[s], rng)
            if done:
                total += step
                reached += 1
                break
    return (total / reached) if reached else float("inf")


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0
