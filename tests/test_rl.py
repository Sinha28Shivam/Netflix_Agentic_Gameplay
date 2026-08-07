"""
test_rl.py — proves the RL layer actually LEARNS, entirely offline
(no device, no VLM, no API key). Run with:

    python -m pytest tests/test_rl.py -v
    (or: python tests/test_rl.py, from the repo root)

Strategy: build the NavigationMDP from the real committed map
(data/maps/bloons_td6.json), compute the optimal policy exactly with value
iteration as ground truth, then train tabular Q-learning against the offline
model and assert it converges to that optimum (zero regret). Also covers the
Q-table save/load round-trip and the RLDecisionAgent drop-in action shape.
"""

import json
import os
import tempfile
import unittest

from src.rl.mdp import NavigationMDP, normalize_target
from src.rl.env import QANavEnv
from src.rl.qlearning import QLearningAgent, value_iteration, expected_steps_to_goal
from src.rl.rl_decision_agent import RLDecisionAgent


MAP_PATH = os.path.join("data", "maps", "bloons_td6.json")


class TestNavigationMDP(unittest.TestCase):
    def setUp(self):
        self.mdp = NavigationMDP.from_file(MAP_PATH, goal_label="in_game")

    def test_states_and_goal(self):
        # The five logical screens collapsed from ~40 hash-suffixed node ids.
        self.assertIn("in_game", self.mdp.states)
        self.assertIn("menu", self.mdp.states)
        self.assertEqual(self.mdp.goal_state, "in_game")
        # far fewer states than raw nodes -> aliasing was collapsed
        self.assertLessEqual(len(self.mdp.states), 8)

    def test_target_normalization(self):
        # OCR noise 'STAnDARD' folds into 'STANDARD'
        self.assertEqual(normalize_target("STAnDARD"), "STANDARD")
        self.assertEqual(normalize_target("STANDARD"), "STANDARD")
        # so there is a single STANDARD action, not two
        targets = [t for _, t in self.mdp.actions]
        self.assertEqual(targets.count("STANDARD"), 1)

    def test_transition_model_is_stochastic(self):
        # menu --MONKEY MEADOW--> is genuinely stochastic in the recorded data
        s = self.mdp.state_index("menu")
        a = self.mdp.action_index("tap", "MONKEY MEADOW")
        self.assertIsNotNone(a)
        outcomes = self.mdp.P[(s, a)]
        self.assertGreater(len(outcomes), 1, "expected a stochastic transition")
        total_p = sum(p for p, *_ in outcomes)
        self.assertAlmostEqual(total_p, 1.0, places=6)


class TestLearning(unittest.TestCase):
    def setUp(self):
        self.mdp = NavigationMDP.from_file(MAP_PATH, goal_label="in_game")

    def test_value_iteration_reaches_goal(self):
        V, policy = value_iteration(self.mdp, gamma=0.95)
        steps = expected_steps_to_goal(self.mdp, policy)
        self.assertLess(steps, 50, "optimal policy should reach the goal reliably")

    def test_qlearning_matches_optimal(self):
        _, vi_policy = value_iteration(self.mdp, gamma=0.95)
        vi_steps = expected_steps_to_goal(self.mdp, vi_policy, seed=1)

        env = QANavEnv(self.mdp, seed=0)
        agent = QLearningAgent(env.n_states, env.n_actions, seed=0)
        stats = agent.train(env, episodes=6000)
        ql_steps = expected_steps_to_goal(self.mdp, agent.policy(), seed=1)

        # Trained near-greedy success rate should be high on this small MDP.
        self.assertGreater(stats["success_rate"], 0.5)
        # Zero-regret: the learned policy is as fast as the exact optimum.
        self.assertLessEqual(ql_steps, vi_steps + 0.5,
                             f"Q-learning ({ql_steps:.2f}) should match VI ({vi_steps:.2f})")

    def test_save_load_roundtrip(self):
        env = QANavEnv(self.mdp, seed=0)
        agent = QLearningAgent(env.n_states, env.n_actions, seed=0)
        agent.train(env, episodes=500)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "qtable.json")
            agent.save(path, mdp=self.mdp)
            self.assertTrue(os.path.exists(path))
            loaded = QLearningAgent.load(path)
            self.assertEqual(loaded.Q, agent.Q)
            self.assertEqual(loaded.epsilon, 0.0)


class TestRLDecisionAgent(unittest.TestCase):
    def setUp(self):
        self.mdp = NavigationMDP.from_file(MAP_PATH, goal_label="in_game")
        env = QANavEnv(self.mdp, seed=0)
        self.agent = QLearningAgent(env.n_states, env.n_actions, seed=0)
        self.agent.train(env, episodes=4000)
        self.rl = RLDecisionAgent(self.mdp, self.agent)

    def test_known_scene_returns_valid_action(self):
        # 'menu' is a real state; expect a DecisionAgent-shaped tap.
        decision = self.rl.decide({"scene": "menu"}, memory=None)
        self.assertIn(decision["action"], ("tap", "swipe_left", "swipe_right", "done", "wait"))
        self.assertIn("why", decision)
        if decision["action"] == "tap":
            self.assertIn("target", decision)

    def test_goal_scene_returns_done(self):
        decision = self.rl.decide({"scene": "in_game"}, memory=None)
        self.assertEqual(decision["action"], "done")

    def test_alias_scene_maps(self):
        # VisionAgent's 'main_menu' aliases to the map's 'menu' state.
        decision = self.rl.decide({"scene": "main_menu"}, memory=None)
        self.assertNotEqual(decision.get("why", ""), "")
        self.assertNotEqual(decision["action"], "wait")  # should be on-policy

    def test_unseen_scene_falls_back_safely(self):
        decision = self.rl.decide({"scene": "totally_unknown_screen"}, memory=None)
        self.assertEqual(decision["action"], "wait")


if __name__ == "__main__":
    unittest.main(verbosity=2)
