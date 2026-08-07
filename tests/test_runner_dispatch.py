"""
test_runner_dispatch.py — proves TestRunner actually closes the
Plan -> Execute gap: given a TestCase, it drives the route through
ExecutorAgent and dispatches the final state to the correct check
(gameplay rule, compliance oracle/judge, or performance rule) — with
no real device or network involved.
"""

import unittest
from unittest.mock import MagicMock, patch

from src.agents.planning.planner_agent import TestCase
from src.agents.compliance.compliance_agent import ComplianceAgent
from src.agents.execution.performance_agent import PerformanceAgent
from src.core.engine.test_runner import TestRunner

# Production code calls time.sleep() between route steps and retries (real
# pacing for a live device). Patched at module level so the test suite
# stays fast — this does not affect what's being tested, only wall-clock cost.
_sleep_patcher = patch("src.core.engine.test_runner.time.sleep", return_value=None)


def make_test_case(**overrides):
    base = dict(
        test_id="bloons_test_01",
        title="Title Screen Navigation",
        category="gameplay",
        target_screen="main_menu",
        route=[{"action": "tap", "target": "Play"}],
        check_fn="assert_screen_reached_with_currency_visible",
        check_args={"required_fields": ["cash"]},
        requires_ai_judge=False,
        source_requirement_id="test_01_title_navigation",
    )
    base.update(overrides)
    return TestCase(**base)


class FakeExecutorAgent:
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = []

    def execute(self, action, state):
        self.calls.append(action)
        return self.succeed


class TestRunnerDispatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _sleep_patcher.start()

    @classmethod
    def tearDownClass(cls):
        _sleep_patcher.stop()

    def setUp(self):
        self.client = MagicMock()
        self.compliance = ComplianceAgent(self.client)
        self.performance = PerformanceAgent()

    def _make_runner(self, executor, states):
        """states: list of state dicts returned by successive capture_state() calls."""
        state_iter = iter(states)

        def capture_state_fn():
            try:
                return next(state_iter)
            except StopIteration:
                return states[-1]

        return TestRunner(
            vision_agent=MagicMock(),
            executor_agent=executor,
            compliance_agent=self.compliance,
            performance_agent=self.performance,
            capture_state_fn=capture_state_fn,
        )

    @patch("src.device.device.get_screenshot_base64", return_value="fake_b64")
    def test_gameplay_route_runs_and_passes(self, _mock_screenshot):
        tc = make_test_case()
        executor = FakeExecutorAgent(succeed=True)
        states = [
            {"scene": "loading"},                                  # capture during retry check
            {"scene": "main_menu", "resources": {"cash": 650}},     # final state after route
        ]
        runner = self._make_runner(executor, states)

        result = runner.run(tc)

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.route_steps_executed, 1)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(executor.calls[0]["target"], "Play")

    @patch("src.device.device.get_screenshot_base64", return_value="fake_b64")
    def test_gameplay_check_fails_when_field_missing(self, _mock_screenshot):
        tc = make_test_case()
        executor = FakeExecutorAgent(succeed=True)
        states = [
            {"scene": "loading"},
            {"scene": "main_menu", "resources": {}},  # cash missing
        ]
        runner = self._make_runner(executor, states)

        result = runner.run(tc)

        self.assertEqual(result.status, "FAIL")
        self.assertIn("cash", result.reason)

    @patch("src.device.device.get_screenshot_base64", return_value="fake_b64")
    def test_route_execution_failure_returns_error_not_silent_pass(self, _mock_screenshot):
        tc = make_test_case()
        executor = FakeExecutorAgent(succeed=False)  # every tap fails
        states = [{"scene": "loading"}] * 10
        runner = self._make_runner(executor, states)

        result = runner.run(tc)

        self.assertEqual(result.status, "ERROR")
        self.assertIn("Route step", result.reason)

    @patch("src.device.device.get_screenshot_base64", return_value="fake_b64")
    def test_landing_on_wrong_screen_is_error_not_misreported_fail(self, _mock_screenshot):
        tc = make_test_case(target_screen="placement")
        executor = FakeExecutorAgent(succeed=True)
        states = [
            {"scene": "loading"},
            {"scene": "main_menu"},  # route completed but wrong screen reached
        ]
        runner = self._make_runner(executor, states)

        result = runner.run(tc)

        self.assertEqual(result.status, "ERROR")
        self.assertIn("MapGap", result.reason)

    @patch("src.device.device.get_screenshot_base64", return_value="fake_b64")
    def test_compliance_category_dispatches_to_compliance_agent(self, _mock_screenshot):
        tc = make_test_case(
            test_id="compliance_01_iap_price_disclosure",
            category="compliance",
            target_screen="main_menu",
            route=[],
            check_fn="assert_iap_modal_shows_price_text",
            check_args={},
            source_requirement_id="compliance_01_iap_price_disclosure",
        )
        executor = FakeExecutorAgent(succeed=True)
        states = [{"scene": "main_menu", "ui_texts": ["Buy Gems", "$4.99"], "actionable_elements": []}]
        runner = self._make_runner(executor, states)

        result = runner.run(tc)

        self.assertEqual(result.category, "compliance")
        self.assertIn(result.status, ("PASS", "FAIL"))  # routed through ComplianceAgent, not gameplay_checks

    @patch("src.device.device.get_screenshot_base64", return_value="fake_b64")
    def test_performance_category_uses_performance_summary(self, _mock_screenshot):
        tc = make_test_case(
            test_id="performance_01_in_round_fps_floor",
            category="performance",
            target_screen="in_round",
            route=[],
            check_fn="assert_fps_above_threshold",
            check_args={"min_fps": 30},
            source_requirement_id="performance_01_in_round_fps_floor",
        )
        executor = FakeExecutorAgent(succeed=True)
        states = [{"scene": "in_round"}]
        runner = self._make_runner(executor, states)

        # Fake an FPS sample directly into the performance summary
        self.performance.summary = MagicMock(return_value={"avg_fps": 45})

        result = runner.run(tc)

        self.assertEqual(result.status, "PASS")
        self.assertIn("45", result.reason)

    def test_unregistered_check_fn_is_error_not_silent_pass(self):
        tc = make_test_case(check_fn="assert_something_never_implemented")
        executor = FakeExecutorAgent(succeed=True)
        with patch("src.device.device.get_screenshot_base64", return_value="fake_b64"):
            states = [{"scene": "loading"}, {"scene": "main_menu", "resources": {"cash": 1}}]
            runner = self._make_runner(executor, states)
            result = runner.run(tc)

        self.assertEqual(result.status, "ERROR")
        self.assertIn("No implementation registered", result.reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
