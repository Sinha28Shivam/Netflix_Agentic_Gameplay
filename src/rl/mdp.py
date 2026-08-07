"""
src/rl/mdp.py — the navigation Markov Decision Process.

The MapStore graph (data/maps/<game>.json) already records, per game, every
screen the Mapper has seen and every (from_screen --action--> to_screen)
transition that worked, with visit counts. That is exactly a tabular MDP:

    state   = a logical screen           (node label, e.g. "menu", "in_game")
    action  = a labelled tap             (e.g. tap "MONKEY MEADOW")
    T(s'|s,a) ∝ edge.seen_count          (a transition's observed frequency)
    reward  = +GOAL on reaching the goal screen, -STEP_COST per move

This module turns that JSON graph into an explicit transition/reward table so
the policy can be trained *offline* — no device, no LLM, no API cost. The same
action vocabulary is emitted in the DecisionAgent JSON shape, so a policy
learned here drops straight onto the live executor.

Design notes tied to the real data (see REINFORCEMENT_LEARNING.md §3):
  - State aliasing: the graph stores ~40 hash-suffixed ids (menu_41956de1, …)
    for the same logical screen, so we COLLAPSE nodes by their `label`.
  - OCR noise: targets arrive as both "STANDARD" and "STAnDARD"; we NORMALISE
    a target to strip()+upper() for matching while keeping a clean display form.
  - The graph is genuinely stochastic (e.g. menu --MONKEY MEADOW--> lands on
    difficulty_select 6/14 of the time and self-loops 8/14), which is why a
    learning agent — not a fixed script — is the right tool.
"""

import json
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Default reward shaping (kept here so reward.py / the MD reference one source).
DEFAULT_GOAL_REWARD = 1.0
DEFAULT_STEP_COST = 0.01
DEFAULT_GOAL_LABEL = "in_game"


def normalize_target(target: Optional[str]) -> str:
    """Canonical key for an action target. Folds OCR noise together:
    'STANDARD' and 'STAnDARD' -> 'STANDARD'. Empty for target-less actions."""
    return (target or "").strip().upper()


def _display_target(target: Optional[str]) -> str:
    """A tidy display/output form for a normalized target ('MONKEY MEADOW')."""
    return normalize_target(target).title() if normalize_target(target) else ""


class NavigationMDP:
    """A finite, tabular MDP over logical screens, built from a MapStore graph.

    Attributes:
        states:  list[str]                 logical screen labels (state space)
        actions: list[tuple[str, str]]     (action_type, normalized_target) pairs
        start_state: str                   where an episode begins
        goal_state:  str                   the screen the QA objective wants
        P: dict[(s_idx, a_idx)] -> list[(prob, next_s_idx, reward, done)]
    """

    def __init__(
        self,
        nodes: Dict[str, dict],
        edges: List[dict],
        goal_label: str = DEFAULT_GOAL_LABEL,
        start_label: Optional[str] = None,
        goal_reward: float = DEFAULT_GOAL_REWARD,
        step_cost: float = DEFAULT_STEP_COST,
    ):
        self.goal_reward = goal_reward
        self.step_cost = step_cost

        # --- collapse nodes to logical states (by label) ---
        id_to_label = {sid: (n.get("label") or sid) for sid, n in nodes.items()}
        labels = sorted(set(id_to_label.values()))
        if goal_label not in labels:
            raise ValueError(
                f"goal label {goal_label!r} not in map (have {labels}). "
                "Pass goal_label= a screen that exists in this game's map."
            )
        self.states: List[str] = labels
        self.goal_state = goal_label
        self._s_index = {s: i for i, s in enumerate(self.states)}

        # --- build the label-level, count-weighted transition table ---
        # counts[(from_label, action_key)][to_label] = summed seen_count
        counts: Dict[Tuple[str, Tuple[str, str]], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        action_set = set()
        for e in edges:
            act = e.get("action", {}) or {}
            a_key = (act.get("action", "tap"), normalize_target(act.get("target")))
            action_set.add(a_key)
            f_lbl = id_to_label.get(e["from_screen"], e["from_screen"])
            t_lbl = id_to_label.get(e["to_screen"], e["to_screen"])
            counts[(f_lbl, a_key)][t_lbl] += int(e.get("seen_count", 1) or 1)

        self.actions: List[Tuple[str, str]] = sorted(action_set)
        self._a_index = {a: i for i, a in enumerate(self.actions)}

        # --- start state ---
        if start_label and start_label in self._s_index:
            self.start_state = start_label
        else:
            self.start_state = self._infer_start(edges, id_to_label)

        # --- materialize P over the FULL state x action space ---
        # An (s, a) with no observed edge is a self-loop (the action did nothing
        # here) — this keeps the MDP complete and well-defined for value iteration.
        self.P: Dict[Tuple[int, int], List[Tuple[float, int, float, bool]]] = {}
        for si, s in enumerate(self.states):
            for ai, a in enumerate(self.actions):
                outs = counts.get((s, a))
                if not outs:
                    self.P[(si, ai)] = [(1.0, si, -self.step_cost, s == self.goal_state)]
                    continue
                total = sum(outs.values())
                transitions = []
                for t_lbl, c in outs.items():
                    ti = self._s_index[t_lbl]
                    done = t_lbl == self.goal_state
                    reward = (self.goal_reward if done else 0.0) - self.step_cost
                    transitions.append((c / total, ti, reward, done))
                self.P[(si, ai)] = transitions

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _infer_start(edges, id_to_label) -> str:
        """Pick the screen with the fewest incoming transitions (ignoring
        self-loops) as the natural entry point — usually 'title'."""
        incoming = defaultdict(int)
        labels = set(id_to_label.values())
        for e in edges:
            f = id_to_label.get(e["from_screen"])
            t = id_to_label.get(e["to_screen"])
            if f != t:
                incoming[t] += 1
        # Prefer a well-known entry label if present.
        for preferred in ("title", "home", "main_menu", "menu"):
            if preferred in labels:
                return preferred
        return min(labels, key=lambda l: incoming.get(l, 0))

    @classmethod
    def from_map(
        cls,
        game_id: str,
        maps_dir: Optional[str] = None,
        **kwargs,
    ) -> "NavigationMDP":
        """Build an MDP from outputs/results/map_store/<game_id>.json (config.MAPS_DIR)."""
        if maps_dir is None:
            try:
                import src.core.config as config
                maps_dir = config.MAPS_DIR
            except Exception:
                maps_dir = "outputs/results/map_store"
        path = os.path.join(maps_dir, f"{game_id}.json")
        return cls.from_file(path, **kwargs)

    @classmethod
    def from_file(cls, path: str, **kwargs) -> "NavigationMDP":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data.get("nodes", {}), data.get("edges", []), **kwargs)

    # ------------------------------------------------------------------
    # Indexing helpers
    # ------------------------------------------------------------------
    def state_index(self, label: str) -> Optional[int]:
        return self._s_index.get(label)

    def action_index(self, action_type: str, target: Optional[str]) -> Optional[int]:
        return self._a_index.get((action_type, normalize_target(target)))

    def action_to_decision(self, a_idx: int, why: str = "RL policy") -> dict:
        """Emit an action in the exact DecisionAgent JSON shape."""
        action_type, target = self.actions[a_idx]
        decision = {"action": action_type, "why": why}
        if target:
            decision["target"] = _display_target(target)
        return decision

    def is_goal(self, s_idx: int) -> bool:
        return self.states[s_idx] == self.goal_state

    # ------------------------------------------------------------------
    # Environment dynamics (used by env.py; pure-python, deterministic given rng)
    # ------------------------------------------------------------------
    def reset_index(self) -> int:
        return self._s_index[self.start_state]

    def step_index(self, s_idx: int, a_idx: int, rng) -> Tuple[int, float, bool]:
        """Sample one transition. `rng` is a random.Random (kept explicit so
        training is reproducible without touching global RNG state)."""
        transitions = self.P[(s_idx, a_idx)]
        r = rng.random()
        cum = 0.0
        for prob, ns, reward, done in transitions:
            cum += prob
            if r <= cum:
                return ns, reward, done
        # floating-point guard: fall back to the last outcome
        prob, ns, reward, done = transitions[-1]
        return ns, reward, done

    def __repr__(self) -> str:
        return (
            f"NavigationMDP(states={len(self.states)}, actions={len(self.actions)}, "
            f"start={self.start_state!r}, goal={self.goal_state!r})"
        )
