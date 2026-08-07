"""
src/rl — Reinforcement Learning for the Netflix Game QA pipeline.

A dependency-light (stdlib + optional numpy) RL layer that learns a navigation
policy from the MapStore transition graph and deploys it on-device as a drop-in
replacement for the (currently unwired) DecisionAgent.

See REINFORCEMENT_LEARNING.md at the repo root for the full design/spec.

Public surface:
    NavigationMDP   — MDP built from data/maps/<game>.json (offline, no device)
    QANavEnv        — Gymnasium-style env wrapping the MDP for training
    QLearningAgent  — tabular Q-learning policy (+ value_iteration baseline)
    RLDecisionAgent — DecisionAgent-compatible policy backed by a trained Q-table
"""

from src.rl.mdp import NavigationMDP
from src.rl.env import QANavEnv
from src.rl.qlearning import QLearningAgent, value_iteration
from src.rl.rl_decision_agent import RLDecisionAgent

__all__ = [
    "NavigationMDP",
    "QANavEnv",
    "QLearningAgent",
    "value_iteration",
    "RLDecisionAgent",
]
