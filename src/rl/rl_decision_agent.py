"""
src/rl/rl_decision_agent.py — the deployable policy.

RLDecisionAgent is a DROP-IN replacement for
src/agents/core/decision_agent.py::DecisionAgent — same `decide(state, memory)`
signature, same JSON action shape — but the action comes from a trained
Q-table instead of an LLM call. No API key, no latency, no cost per decision.

Why this is safe: DecisionAgent is not on the production execution path (the
orchestrator uses the scripted executor). So swapping in a learned policy adds
a real RL controller without changing the running pipeline's default behaviour.
Set USE_RL_POLICY=1 (config) to route the decision loop through it.

State mapping: the live VisionAgent reports a `scene` string
(main_menu, map_selection, in_round, …). We map it to a NavigationMDP state.
When the observed scene isn't a state the policy was trained on, we fall back
to a safe `wait` (or, if a fallback DecisionAgent/LLM client is supplied, we
delegate — a hybrid learned+LLM policy).
"""

from typing import Optional

from src.rl.mdp import NavigationMDP
from src.rl.qlearning import QLearningAgent

# The VisionAgent scene vocabulary doesn't always equal the MapStore node
# labels, so we bridge the two. Extend as new games/maps are added.
SCENE_TO_STATE_ALIASES = {
    "main_menu": "menu",
    "map_selection": "menu",
    "game_mode": "difficulty_select",
    "difficulty_selection": "difficulty_select",
    "placement": "in_game",
    "in_round": "in_game",
    "between_rounds": "in_game",
}


class RLDecisionAgent:
    """Greedy policy over a trained Q-table, emitting DecisionAgent-shaped JSON."""

    def __init__(
        self,
        mdp: NavigationMDP,
        agent: QLearningAgent,
        fallback=None,
    ):
        """
        mdp:      the NavigationMDP the policy was trained on (for index<->label).
        agent:    a trained QLearningAgent (epsilon exploited to 0 on load).
        fallback: optional object with .decide(state, memory) (e.g. the LLM
                  DecisionAgent) used when the observed scene is off-policy.
        """
        self.mdp = mdp
        self.agent = agent
        self.fallback = fallback

    @classmethod
    def from_files(cls, game_id: str, policy_path: Optional[str] = None,
                   maps_dir: Optional[str] = None, fallback=None) -> "RLDecisionAgent":
        """Build from a game's map + a saved Q-table
        (outputs/rl/<game>_qtable.json by default)."""
        mdp = NavigationMDP.from_map(game_id, maps_dir=maps_dir)
        if policy_path is None:
            policy_path = f"outputs/rl/{game_id}_qtable.json"
        agent = QLearningAgent.load(policy_path)
        return cls(mdp, agent, fallback=fallback)

    # -- the DecisionAgent contract --
    def decide(self, state: dict, memory) -> dict:
        s_idx = self._state_index(state)
        if s_idx is None:
            return self._fallback(state, memory,
                                  why="RL: unseen scene -> safe wait")
        if self.mdp.is_goal(s_idx):
            return {"action": "done", "result": "objective_met",
                    "why": f"RL: reached goal scene '{self.mdp.goal_state}'."}
        a_idx = self.agent.greedy_action(s_idx)
        return self.mdp.action_to_decision(
            a_idx, why=f"RL optimal policy from state '{self.mdp.states[s_idx]}'")

    # -- helpers --
    def _state_index(self, state: dict) -> Optional[int]:
        scene = (state or {}).get("scene", "unknown")
        # direct label match first, then alias table
        idx = self.mdp.state_index(scene)
        if idx is not None:
            return idx
        aliased = SCENE_TO_STATE_ALIASES.get(scene)
        return self.mdp.state_index(aliased) if aliased else None

    def _fallback(self, state, memory, why: str) -> dict:
        if self.fallback is not None:
            try:
                return self.fallback.decide(state, memory)
            except Exception:
                pass
        return {"action": "wait", "ms": 2000, "why": why}
