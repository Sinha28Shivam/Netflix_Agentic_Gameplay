#!/usr/bin/env python3
"""
run_plan.py — the missing connection: loads the JSON test plan
map_and_plan.py plan produced, and actually runs every TestCase against
a live device via TestRunner, writing one combined report.

This is what makes map_and_plan.py's output and orchestrator.py's
perception/execution stack one connected pipeline instead of two
pipelines that happen to share code:

    python map_and_plan.py seed   --game bloons_td6 --actions seed_scripts/bloons_seed.json
    python map_and_plan.py plan   --game bloons_td6
    python run_plan.py            --game bloons_td6      <-- this file

Usage:
    python run_plan.py --game bloons_td6 --plans-dir plans
"""

import argparse
import json
import os
import time

from openai import OpenAI

import src.core.config as config
from src.device.device import get_current_app, get_screenshot_base64, get_ui_texts, launch_game

from src.agents.compliance.compliance_agent import ComplianceAgent
from src.agents.execution.executor_agent import ExecutorAgent
from src.agents.execution.performance_agent import PerformanceAgent
from src.agents.planning.planner_agent import TestCase
from src.core.engine.test_runner import TestRunner, run_test_plan
from src.agents.core.vision_agent import VisionAgent


def load_test_plan(game_id: str, plans_dir: str):
    path = os.path.join(plans_dir, f"{game_id}_test_plan.json")
    if not os.path.exists(path):
        raise SystemExit(
            f"No test plan found at {path}. Run "
            f"`python map_and_plan.py plan --game {game_id}` first."
        )
    with open(path) as f:
        data = json.load(f)
    return [TestCase(**tc) for tc in data["test_cases"]], data.get("skipped_requirements", [])


def make_capture_state_fn(vision_agent):
    def capture_state():
        screenshot_b64 = get_screenshot_base64()
        ui_texts = get_ui_texts()
        state = vision_agent.observe(screenshot_b64, ui_texts)
        state["ui_texts"] = ui_texts
        state["current_app"] = get_current_app()
        return state
    return capture_state


def main():
    parser = argparse.ArgumentParser(description="Run a generated test plan against a live device")
    parser.add_argument("--game", required=True)
    parser.add_argument("--plans-dir", default="plans")
    parser.add_argument("--ensure-game-running", action="store_true", default=True)
    args = parser.parse_args()

    test_cases, skipped = load_test_plan(args.game, args.plans_dir)
    if skipped:
        print(f"⚠ {len(skipped)} requirement(s) were skipped at plan time (MapGap) — not run here:")
        for s in skipped:
            print(f"   - {s['requirement_id']}: {s['reason']}")

    client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    vision_agent = VisionAgent(client)
    executor = ExecutorAgent()
    compliance = ComplianceAgent(client)
    performance = PerformanceAgent()
    capture_state = make_capture_state_fn(vision_agent)

    if args.ensure_game_running:
        state = capture_state()
        if config.GAME_PACKAGE.lower() not in state.get("current_app", "").lower():
            print("⚠ Game not running — launching")
            launch_game()
            time.sleep(5)

    runner = TestRunner(
        vision_agent=vision_agent,
        executor_agent=executor,
        compliance_agent=compliance,
        performance_agent=performance,
        capture_state_fn=capture_state,
    )

    results = run_test_plan(test_cases, runner)

    summary = {
        "game": args.game,
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "PASS"),
        "failed": sum(1 for r in results if r.status == "FAIL"),
        "errored": sum(1 for r in results if r.status == "ERROR"),
        "pending_human_review": sum(1 for r in results if r.needs_human_review),
        "skipped_at_plan_time": len(skipped),
    }

    report = {
        "summary": summary,
        "results": [vars(r) for r in results],
        "skipped_requirements": skipped,
        "compliance_summary": compliance.summary(),
        "performance_summary": performance.summary(),
    }

    os.makedirs(config.REPORT_DIR, exist_ok=True)
    path = os.path.join(config.REPORT_DIR, f"plan_run_{args.game}_{int(time.time())}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 60)
    print(f"  {summary['passed']} PASS / {summary['failed']} FAIL / {summary['errored']} ERROR "
          f"({summary['pending_human_review']} pending human review)")
    print(f"  Report: {path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
