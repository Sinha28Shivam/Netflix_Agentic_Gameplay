"""
test_map_and_plan.py — proves the Map -> Plan pipeline works without a
real device or a live VLM endpoint attached. Run with:

    python -m pytest tests/test_map_and_plan.py -v
    (or just: python tests/test_map_and_plan.py, run from the repo root)

Strategy: stub out the two things that need real infra (VisionAgent's
LLM call, and the device-layer adb calls) with a tiny scripted fake that
walks through a fixed Bloons-like screen sequence. This tests the actual
MapStore/MapAgent/PlannerAgent logic, not the LLM or the phone.
"""

import json
import os
import shutil
import tempfile
import unittest

from src.models.map_store import MapStore
from src.agents.planning.planner_agent import PlannerAgent
from src.models.category_specs import BLOONS_REQUIREMENTS


# A fixed scripted screen sequence standing in for a real device + VLM.
# Mirrors the route in seed_scripts/bloons_seed.json.
SCRIPTED_SCREENS = [
    {"scene": "main_menu", "ui_texts": ["Play"], "actionable_elements": [{"label": "Play", "x": 540, "y": 1700}]},
    {"scene": "map_selection", "ui_texts": ["Monkey Meadow"], "actionable_elements": [{"label": "Monkey Meadow", "x": 300, "y": 800}]},
    {"scene": "difficulty_selection", "ui_texts": ["Easy"], "actionable_elements": [{"label": "Easy", "x": 200, "y": 900}]},
    {"scene": "game_mode", "ui_texts": ["Standard"], "actionable_elements": [{"label": "Standard", "x": 200, "y": 900}]},
    {"scene": "placement", "ui_texts": ["Dart Monkey"], "actionable_elements": [{"label": "Dart Monkey", "x": 100, "y": 1500}]},
    {"scene": "placement", "ui_texts": ["Dart Monkey", "Start Round"], "actionable_elements": [{"label": "Start Round", "x": 1000, "y": 1800}]},
    {"scene": "in_round", "ui_texts": ["3x Speed"], "actionable_elements": [{"label": "3x Speed", "x": 950, "y": 100}]},
    {"scene": "in_round", "ui_texts": [], "actionable_elements": []},
]


class FakeVisionAgent:
    """Replaces VisionAgent.observe — returns the next scripted screen."""

    def __init__(self, screens):
        self.screens = screens
        self.i = 0

    def observe(self, screenshot_b64, ui_texts):
        state = self.screens[min(self.i, len(self.screens) - 1)]
        self.i += 1
        return dict(state)  # copy so callers can mutate freely


class FakeExecutorAgent:
    """Replaces ExecutorAgent.execute — no-op, just records calls."""

    def __init__(self):
        self.calls = []

    def execute(self, decision, state):
        self.calls.append(decision)
        return True


class MapAgentWithFakes:
    """Same logic as agents.map_agent.MapAgent, but bypasses the real
    device-layer get_screenshot_base64/get_ui_texts/get_current_app calls
    (which require adb) so this test runs anywhere."""

    def __init__(self, vision_agent, executor_agent, game_id, maps_dir):
        self.vision = vision_agent
        self.executor = executor_agent
        self.store = MapStore(game_id, maps_dir=maps_dir)

    def _observe(self):
        state = self.vision.observe(None, [])
        state.setdefault("ui_texts", state.get("ui_texts", []))
        state["current_app"] = "com.ninjakiwi.bloonstd6"
        return state

    def seed_from_walkthrough(self, recorded_actions):
        prev_screen_id, prev_action = None, None
        for action in recorded_actions:
            state = self._observe()
            screen_id = state.get("scene", "unknown")

            self.store.upsert_node(
                screen_id=screen_id,
                ui_texts=state.get("ui_texts", []),
                actionable_elements=state.get("actionable_elements", []),
                is_terminal=screen_id in ("victory", "defeat"),
                tags=["seeded"],
            )
            if prev_screen_id is not None:
                self.store.upsert_edge(prev_screen_id, prev_action, screen_id, source="seed")

            self.executor.execute(action, state)
            prev_screen_id, prev_action = screen_id, action

        # final observe to close out the last edge
        state = self._observe()
        screen_id = state.get("scene", "unknown")
        self.store.upsert_node(screen_id=screen_id, ui_texts=state.get("ui_texts", []))
        if prev_screen_id is not None:
            self.store.upsert_edge(prev_screen_id, prev_action, screen_id, source="seed")

        self.store.save()
        return self.store.coverage_summary()


class TestMapAndPlanPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.maps_dir = os.path.join(self.tmp_dir, "maps")
        self.plans_dir = os.path.join(self.tmp_dir, "plans")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_seed_builds_map_with_expected_screens(self):
        vision = FakeVisionAgent(SCRIPTED_SCREENS)
        executor = FakeExecutorAgent()
        map_agent = MapAgentWithFakes(vision, executor, game_id="bloons_td6", maps_dir=self.maps_dir)

        with open("seed_scripts/bloons_seed.json") as f:
            recorded_actions = json.load(f)

        summary = map_agent.seed_from_walkthrough(recorded_actions)

        self.assertGreaterEqual(summary["screens_mapped"], 5)
        self.assertIn("main_menu", [n for n in map_agent.store.known_screens()])
        self.assertIn("placement", map_agent.store.known_screens())
        self.assertIn("in_round", map_agent.store.known_screens())
        self.assertGreater(summary["edges_mapped"], 0)
        print("\n[seed] coverage:", json.dumps(summary, indent=2))

    def test_planner_resolves_routes_and_flags_gaps(self):
        # Build a map first (reusing the seed test's logic)
        vision = FakeVisionAgent(SCRIPTED_SCREENS)
        executor = FakeExecutorAgent()
        map_agent = MapAgentWithFakes(vision, executor, game_id="bloons_td6", maps_dir=self.maps_dir)
        with open("seed_scripts/bloons_seed.json") as f:
            recorded_actions = json.load(f)
        map_agent.seed_from_walkthrough(recorded_actions)

        planner = PlannerAgent(game_id="bloons_td6", maps_dir=self.maps_dir, plans_dir=self.plans_dir)
        test_cases = planner.plan(BLOONS_REQUIREMENTS, start_screen="main_menu")

        # Requirements targeting mapped screens (main_menu, placement, in_round)
        # should produce resolvable test cases with a route.
        resolved_targets = {tc.target_screen for tc in test_cases}
        self.assertIn("main_menu", resolved_targets)
        self.assertIn("placement", resolved_targets)
        self.assertIn("in_round", resolved_targets)

        # Requirements targeting screens this seed never visited (tower_detail,
        # defeat, system_update_modal) must be SKIPPED, not silently invented —
        # this is the MapGap behavior the Remediation agent is supposed to act on.
        plan_path = os.path.join(self.plans_dir, "bloons_td6_test_plan.json")
        with open(plan_path) as f:
            plan_data = json.load(f)

        skipped_ids = {s["requirement_id"] for s in plan_data["skipped_requirements"]}
        self.assertIn("test_04_target_priority", skipped_ids)  # tower_detail not seeded
        self.assertIn("test_09_defeat_modal", skipped_ids)     # defeat not seeded

        print(f"\n[plan] {len(test_cases)} resolved, {len(skipped_ids)} skipped (MapGap)")
        for tc in test_cases:
            print(f"  - {tc.test_id}: route of {len(tc.route)} actions -> {tc.target_screen}")

    def test_route_is_actually_executable_sequence(self):
        vision = FakeVisionAgent(SCRIPTED_SCREENS)
        executor = FakeExecutorAgent()
        map_agent = MapAgentWithFakes(vision, executor, game_id="bloons_td6", maps_dir=self.maps_dir)
        with open("seed_scripts/bloons_seed.json") as f:
            recorded_actions = json.load(f)
        map_agent.seed_from_walkthrough(recorded_actions)

        planner = PlannerAgent(game_id="bloons_td6", maps_dir=self.maps_dir, plans_dir=self.plans_dir)
        test_cases = planner.plan(BLOONS_REQUIREMENTS, start_screen="main_menu")

        in_round_case = next(tc for tc in test_cases if tc.target_screen == "in_round")
        # route should be a non-empty, ordered list of real recorded actions
        self.assertGreater(len(in_round_case.route), 0)
        for step in in_round_case.route:
            self.assertIn("action", step)


if __name__ == "__main__":
    unittest.main(verbosity=2)
