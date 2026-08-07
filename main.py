#!/usr/bin/env python3
"""
main.py — thin entry point over the custom orchestrator.

Usage:
    python main.py                 # Full run: setup ONLY if new game, then the
                                   #   parallel test cycle (gameplay ∥ compliance
                                   #   ∥ performance) -> Validator -> Recovery -> Report
    python main.py --force-setup   # Same, but re-run Mapper+Planner even if mapped
    python main.py --map           # Run only Stage 1: Map
    python main.py --plan          # Run only Stage 2: Plan
    python main.py --execute       # Run only Stage 3: the parallel test cycle
    python main.py --report        # Run only Stage 4: Report (from results.json)

The Mapper/Planner (setup) run once per new game; everything else runs every
cycle. See orchestrator.py for the flow.
"""

import argparse
import os
import sys


def run_mapper() -> bool:
    print("\n" + "=" * 70 + "\nSTAGE 1: MAP\n" + "=" * 70)
    try:
        from src.agents.planning.map_agent import MapAgent
        MapAgent().build_map()
        if not os.path.exists("outputs/results/map_store.json"):
            print("Map stage failed: map_store.json was not created.")
            return False
        print("Map stage complete. -> map_store.json")
        return True
    except Exception as e:
        print(f"Map stage failed: {e}")
        import traceback; traceback.print_exc()
        return False


def run_planner() -> bool:
    print("\n" + "=" * 70 + "\nSTAGE 2: PLAN\n" + "=" * 70)
    if not os.path.exists("outputs/results/map_store.json"):
        print("map_store.json not found. Run map stage first.")
        return False
    try:
        from src.agents.planning.planner_agent import PlannerAgent
        PlannerAgent().build_plan()
        if not os.path.exists("outputs/results/test_plan.json"):
            print("Plan stage failed: test_plan.json was not created.")
            return False
        print("Plan stage complete. -> test_plan.json")
        return True
    except Exception as e:
        print(f"Plan stage failed: {e}")
        import traceback; traceback.print_exc()
        return False


def run_executor() -> bool:
    print("\n" + "=" * 70 + "\nSTAGE 3: EXECUTE (parallel cycle)\n" + "=" * 70)
    if not os.path.exists("outputs/results/test_plan.json"):
        print("test_plan.json not found. Run setup (map+plan) first.")
        return False
    try:
        from src.core.orchestrator import run_cycle_and_report
        return run_cycle_and_report(write_report=False)
    except Exception as e:
        print(f"Execute stage failed: {e}")
        import traceback; traceback.print_exc()
        return False


def run_reporter() -> bool:
    print("\n" + "=" * 70 + "\nSTAGE 4: REPORT\n" + "=" * 70)
    if not os.path.exists("outputs/results/results.json"):
        print("results.json not found. Run execute stage first.")
        return False
    try:
        from src.agents.evaluation.report_agent import generate_report
        path = generate_report()
        if not path:
            print("Report stage failed: no report was written.")
            return False
        print(f"Report stage complete. -> {path}")
        return True
    except Exception as e:
        print(f"Report stage failed: {e}")
        import traceback; traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="Agentic Game QA — Orchestrated Pipeline")
    parser.add_argument("--game", default=os.environ.get("GAME_ID", "bloons_td6"),
                        help="Which registered game plugin to run (default: bloons_td6)")
    parser.add_argument("--map",         action="store_true", help="Run Stage 1: Map only")
    parser.add_argument("--plan",        action="store_true", help="Run Stage 2: Plan only")
    parser.add_argument("--execute",     action="store_true", help="Run Stage 3: parallel test cycle only")
    parser.add_argument("--report",      action="store_true", help="Run Stage 4: Report only")
    parser.add_argument("--force-setup", action="store_true",
                        help="Re-run Mapper+Planner even if the game is already mapped")
    parser.add_argument("--execute-setup", action="store_true",
                        help="Run setup phase (Mapper+Planner) for first time / forced setup")
    args = parser.parse_args()

    # Bind the active game BEFORE the (lazy) agent/orchestrator imports below.
    os.environ["GAME_ID"] = args.game

    force_setup = args.force_setup or args.execute_setup

    granular = args.map or args.plan or args.execute or args.report
    if not granular:
        # Default: orchestrator decides setup-once vs cycle, then reports.
        from src.core.orchestrator import run
        ok = run(force_setup=force_setup)
        sys.exit(0 if ok else 1)

    if args.map and not run_mapper():
        sys.exit(1)
    if args.plan and not run_planner():
        sys.exit(1)
    if args.execute and not run_executor():
        sys.exit(1)
    if args.report and not run_reporter():
        sys.exit(1)

    print("\n" + "=" * 70 + "\nDONE\n" + "=" * 70)


if __name__ == "__main__":
    print("\nStarting Agentic Game QA Pipeline...")
    main()
