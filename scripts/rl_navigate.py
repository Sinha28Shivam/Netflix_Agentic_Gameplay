#!/usr/bin/env python3
"""
scripts/rl_navigate.py — drive a live device with the trained RL policy.

Mirrors scripts/run_plan.py's wiring, but the per-step action comes from
RLDecisionAgent (a trained Q-table) instead of a scripted route or an LLM.
It steps the LiveDeviceEnv until the goal scene is reached or max steps hit,
proving the offline-trained policy transfers to a real device.

    # 1. train offline (no device):
    python -m src.rl.train --game bloons_td6 --episodes 5000
    # 2. then, with a device attached:
    python scripts/rl_navigate.py --game bloons_td6

Requires: an Android device on ADB, the game installed, and (for perception)
a configured LLM client — same prerequisites as run_plan.py.
"""

import argparse
import os
import sys

# Ensure the root directory is on the path so 'src' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import src.core.config as config
from src.rl.mdp import NavigationMDP
from src.rl.qlearning import QLearningAgent
from src.rl.rl_decision_agent import RLDecisionAgent
from src.rl.env import LiveDeviceEnv


def _make_client():
    """Same client construction run_plan.py uses (OpenAI-compatible shim)."""
    from openai import OpenAI
    return OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Navigate a live device with a trained RL policy")
    ap.add_argument("--game", default="bloons_td6")
    ap.add_argument("--policy", default=None, help="Q-table path (default outputs/rl/<game>_qtable.json)")
    ap.add_argument("--max-steps", type=int, default=40)
    args = ap.parse_args(argv)

    policy_path = args.policy or f"outputs/rl/{args.game}_qtable.json"
    if not os.path.exists(policy_path):
        raise SystemExit(f"No trained policy at {policy_path}. Run "
                         f"`python -m src.rl.train --game {args.game}` first.")

    mdp = NavigationMDP.from_map(args.game)
    agent = QLearningAgent.load(policy_path)
    rl = RLDecisionAgent(mdp, agent)

    client = _make_client()
    env = LiveDeviceEnv(mdp, client=client, max_steps=args.max_steps)

    print(f"Navigating {args.game} with RL policy toward '{mdp.goal_state}' …")
    state = env.reset()
    for step in range(1, args.max_steps + 1):
        if state is None:
            # off-policy scene: let RLDecisionAgent choose its safe fallback,
            # translate to an action index if it maps, else just re-observe.
            print(f"  step {step}: scene off-policy — re-observing")
            state, _, done, trunc, _ = env.step(0)
            continue
        action = agent.greedy_action(state)
        state, reward, done, truncated, info = env.step(action)
        print(f"  step {step}: {info['decision']}  -> scene={info['scene']}  r={reward:+.3f}")
        if done:
            print(f"reached goal scene '{mdp.goal_state}' in {step} steps")
            return
        if truncated:
            break
    print("did not reach the goal within max steps")


if __name__ == "__main__":
    main()
