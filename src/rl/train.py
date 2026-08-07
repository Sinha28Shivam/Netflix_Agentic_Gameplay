"""
src/rl/train.py — train a navigation policy offline and save it.

Builds a NavigationMDP from a game's MapStore graph, trains a tabular
Q-learning agent against the offline model, prints convergence stats and the
learned optimal path (compared against the value-iteration optimum), and writes
the Q-table to outputs/rl/<game>_qtable.json for RLDecisionAgent to load.

    python -m src.rl.train --game bloons_td6 --episodes 5000

No device, no LLM, no API key required — training is pure computation over the
recorded transition graph.
"""

import argparse
import os

from src.rl.mdp import NavigationMDP
from src.rl.env import QANavEnv
from src.rl.qlearning import QLearningAgent, value_iteration, expected_steps_to_goal


def _path_str(mdp: NavigationMDP, policy) -> str:
    """Render the greedy path start -> goal as 'state --action--> …'."""
    import random
    rng = random.Random(0)
    s = mdp.reset_index()
    parts = [mdp.states[s]]
    for _ in range(20):
        a = policy[s]
        act_type, target = mdp.actions[a]
        label = f"{act_type} {target}".strip()
        ns, _, done = mdp.step_index(s, a, rng)
        parts.append(f"--{label}--> {mdp.states[ns]}")
        s = ns
        if done:
            break
    return " ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train an offline RL navigation policy")
    ap.add_argument("--game", default="bloons_td6", help="game id (matches outputs/results/map_store/<game>.json)")
    ap.add_argument("--episodes", type=int, default=5000)
    ap.add_argument("--goal", default="in_game", help="goal screen label")
    ap.add_argument("--maps-dir", default=None, help="override maps dir (default config.MAPS_DIR)")
    ap.add_argument("--out", default=None, help="output Q-table path")
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--gamma", type=float, default=0.95)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    mdp = NavigationMDP.from_map(args.game, maps_dir=args.maps_dir, goal_label=args.goal)
    print(f"MDP: {mdp}")
    print(f"  states : {mdp.states}")
    print(f"  actions: {[f'{t} {tg}'.strip() for t, tg in mdp.actions]}")

    # Exact baseline (ground truth) from the model.
    V, vi_policy = value_iteration(mdp, gamma=args.gamma)
    vi_steps = expected_steps_to_goal(mdp, vi_policy, seed=args.seed)
    print(f"\nValue iteration (optimal):")
    print(f"  path      : {_path_str(mdp, vi_policy)}")
    print(f"  mean taps : {vi_steps:.2f}")

    # Learn it from experience.
    env = QANavEnv(mdp, seed=args.seed)
    agent = QLearningAgent(env.n_states, env.n_actions, alpha=args.alpha,
                           gamma=args.gamma, seed=args.seed)
    stats = agent.train(env, episodes=args.episodes)
    ql_policy = agent.policy()
    ql_steps = expected_steps_to_goal(mdp, ql_policy, seed=args.seed)

    print(f"\nQ-learning ({args.episodes} episodes):")
    print(f"  success_rate       : {stats['success_rate']:.3f}")
    print(f"  mean_return_last100: {stats['mean_return_last_100']:.3f}")
    print(f"  learned path       : {_path_str(mdp, ql_policy)}")
    print(f"  mean taps          : {ql_steps:.2f}")
    match = "MATCHES optimal [OK]" if abs(ql_steps - vi_steps) < 0.5 else "DIFFERS from optimal [!]"
    print(f"  vs value iteration : {match}")

    out = args.out or f"outputs/rl/{args.game}_qtable.json"
    agent.save(out, mdp=mdp)
    print(f"\nSaved Q-table -> {out}")
    return out


if __name__ == "__main__":
    main()
