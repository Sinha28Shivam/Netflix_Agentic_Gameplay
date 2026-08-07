#!/usr/bin/env python3
"""
Entry point for the Map + Plan pipeline (the two stages the original
prototype didn't have).

Usage:
    # 1. Seed a game's map from a recorded action log (reproducible, demo-able)
    python map_and_plan.py seed --game bloons_td6 --actions seed_scripts/bloons_seed.json

    # 2. Autonomously patch any gaps left in the map (no human, no recording)
    python map_and_plan.py explore --game bloons_td6

    # 3. Generate the test plan from a structured spec + the map
    python map_and_plan.py plan --game bloons_td6

This intentionally stays a separate CLI from main.py: main.py's
QAOrchestrator EXECUTES a single mission against a running device.
This script builds the map and plan that mission would come from.
In the full architecture they're stage 1/2 and stage 3 of one
pipeline; kept separate here so each can be demoed/tested independently
of having a live device attached.
"""

import argparse
import json

# Resolve --game into GAME_ID before importing anything that binds the active
# game (map_agent resolves the active game's name/package at import time).
from src.core.game_select import select_game_from_argv
select_game_from_argv()

import src.core.config as config
from src.games.registry import get_game
from src.agents.planning.map_agent import MapAgent
from src.models.map_store import MapStore
from src.agents.planning.planner_agent import PlannerAgent
from src.agents.core.vision_agent import VisionAgent
from src.agents.execution.executor_agent import ExecutorAgent
from openai import OpenAI


def cmd_seed(args):
    client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    vision = VisionAgent(client)
    executor = ExecutorAgent()
    map_agent = MapAgent(vision, executor, game_id=args.game, maps_dir=args.maps_dir)

    recorded_actions = None
    if args.actions:
        with open(args.actions) as f:
            recorded_actions = json.load(f)

    summary = map_agent.seed_from_walkthrough(recorded_actions=recorded_actions)
    print(json.dumps(summary, indent=2))


def cmd_explore(args):
    client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    vision = VisionAgent(client)
    executor = ExecutorAgent()
    map_agent = MapAgent(vision, executor, game_id=args.game, maps_dir=args.maps_dir)

    summary = map_agent.explore_gaps(max_new_edges=args.max_new_edges)
    print(json.dumps(summary, indent=2))


def cmd_plan(args):
    planner = PlannerAgent(game_id=args.game, maps_dir=args.maps_dir, plans_dir=args.plans_dir)

    # Requirements come from the registered game plugin. Adding game #2 means
    # dropping a new package under src/games/<id>/ — no edit here — this is the
    # "extensibility" claim made literal.
    try:
        requirements = get_game(args.game).build_requirements()
    except KeyError as e:
        raise SystemExit(str(e))

    test_cases = planner.plan(requirements, start_screen=args.start_screen)
    print(f"Generated {len(test_cases)} test cases for {args.game}")


def cmd_coverage(args):
    store = MapStore(args.game, maps_dir=args.maps_dir)
    print(json.dumps(store.coverage_summary(), indent=2))


def main():
    parser = argparse.ArgumentParser(description="Map + Plan pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="Seed a game's map from a guided pass or recording")
    p_seed.add_argument("--game", required=True)
    p_seed.add_argument("--actions", help="Path to a JSON action log to replay")
    p_seed.add_argument("--maps-dir", default="maps")
    p_seed.set_defaults(func=cmd_seed)

    p_explore = sub.add_parser("explore", help="Autonomously patch gaps in an existing map")
    p_explore.add_argument("--game", required=True)
    p_explore.add_argument("--maps-dir", default="maps")
    p_explore.add_argument("--max-new-edges", type=int, default=15)
    p_explore.set_defaults(func=cmd_explore)

    p_plan = sub.add_parser("plan", help="Generate a test plan from specs + the map")
    p_plan.add_argument("--game", required=True)
    p_plan.add_argument("--maps-dir", default="maps")
    p_plan.add_argument("--plans-dir", default="plans")
    p_plan.add_argument("--start-screen", default="main_menu")
    p_plan.set_defaults(func=cmd_plan)

    p_cov = sub.add_parser("coverage", help="Print map coverage summary for a game")
    p_cov.add_argument("--game", required=True)
    p_cov.add_argument("--maps-dir", default="maps")
    p_cov.set_defaults(func=cmd_coverage)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
