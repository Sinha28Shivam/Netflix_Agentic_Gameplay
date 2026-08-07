"""
test_compliance_split.py — proves the deterministic-oracle /
ambiguous-judge split actually behaves as claimed, with no network
or real VLM endpoint needed.

Three things this test must demonstrate or the rewrite hasn't earned
the "deterministic-first" claim:
  1. Exact checks (price text, age-gate phrase, tap-target size) return
     identical results every run given identical input — no model call
     involved at all.
  2. The judge is ONLY invoked for the four registered ambiguous checks,
     never asked a free-form "find compliance issues" question.
  3. A low-confidence judge verdict does NOT get counted as a pass or a
     fail in summary() — it lands in pending_human_review instead.
"""

import json
import unittest
from unittest.mock import MagicMock

from src.agents.compliance.compliance_oracle import ComplianceOracle
from src.core.engine.verification_judge import VerificationJudge, AMBIGUOUS_CHECK_REGISTRY
from src.agents.compliance.compliance_agent import ComplianceAgent


def fake_openai_response(verdict="pass", confidence=0.9, reasoning="looks fine"):
    """Builds a MagicMock shaped like an OpenAI chat completion response."""
    payload = json.dumps({"verdict": verdict, "confidence": confidence, "reasoning": reasoning})
    msg = MagicMock()
    msg.content = payload
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


class TestComplianceOracle(unittest.TestCase):
    """Pure rule checks — no model involved, deterministic by construction."""

    def setUp(self):
        self.oracle = ComplianceOracle()

    def test_iap_price_check_passes_with_price_text(self):
        finding = self.oracle.assert_iap_modal_shows_price_text(
            scene="dialog", ui_texts=["Buy 500 Gems", "$4.99", "Cancel"]
        )
        self.assertTrue(finding.passed)
        self.assertTrue(finding.deterministic)

    def test_iap_price_check_fails_without_price_text(self):
        finding = self.oracle.assert_iap_modal_shows_price_text(
            scene="dialog", ui_texts=["Buy 500 Gems", "Confirm Purchase", "Cancel"]
        )
        self.assertFalse(finding.passed)

    def test_iap_check_is_deterministic_across_repeated_calls(self):
        ui_texts = ["Buy 500 Gems", "$4.99", "Cancel"]
        results = [self.oracle.assert_iap_modal_shows_price_text("dialog", ui_texts).passed for _ in range(10)]
        self.assertEqual(len(set(results)), 1, "exact check must return identical result every time")

    def test_age_gate_phrase_match(self):
        passing = self.oracle.assert_age_gate_text_present("main_menu", ["Please confirm your date of birth"])
        failing = self.oracle.assert_age_gate_text_present("main_menu", ["Play", "Settings"])
        self.assertTrue(passing.passed)
        self.assertFalse(failing.passed)

    def test_tap_target_size_uses_exact_pixel_comparison(self):
        elements = [{"label": "Play", "width": 40, "height": 40}, {"label": "Settings", "width": 60, "height": 60}]
        finding = self.oracle.assert_tap_targets_meet_minimum_size("main_menu", elements, min_px=48)
        self.assertFalse(finding.passed)
        self.assertEqual(finding.evidence["undersized_labels"], ["Play"])

    def test_splash_duration_exact_window(self):
        in_range = self.oracle.assert_splash_duration_in_range(0.0, 2.0, min_ms=1800, max_ms=2200)
        too_short = self.oracle.assert_splash_duration_in_range(0.0, 1.0, min_ms=1800, max_ms=2200)
        self.assertTrue(in_range.passed)
        self.assertFalse(too_short.passed)


class TestVerificationJudgeRouting(unittest.TestCase):
    """Confirms the judge only answers registered ambiguous questions and
    respects the confidence gate."""

    def test_rejects_unregistered_check_id(self):
        client = MagicMock()
        judge = VerificationJudge(client)
        with self.assertRaises(ValueError):
            judge.judge("fake_b64", "main_menu", "some_made_up_check")

    def test_high_confidence_verdict_is_not_queued(self):
        client = MagicMock()
        client.chat.completions.create.return_value = fake_openai_response(verdict="pass", confidence=0.95)
        judge = VerificationJudge(client, confidence_threshold=0.75)

        finding = judge.judge("fake_b64", "main_menu", "text_contrast_adequate")

        self.assertEqual(finding.verdict, "pass")
        self.assertFalse(finding.needs_human_review)
        self.assertEqual(len(judge.pending_human_review()), 0)

    def test_low_confidence_verdict_is_queued_not_counted(self):
        client = MagicMock()
        client.chat.completions.create.return_value = fake_openai_response(verdict="fail", confidence=0.4)
        judge = VerificationJudge(client, confidence_threshold=0.75)

        finding = judge.judge("fake_b64", "main_menu", "ad_clearly_labeled")

        self.assertEqual(finding.verdict, "needs_human_review")
        self.assertTrue(finding.needs_human_review)
        self.assertEqual(len(judge.pending_human_review()), 1)

    def test_malformed_response_is_zero_confidence_not_silent_fail(self):
        client = MagicMock()
        bad_response = MagicMock()
        bad_msg = MagicMock()
        bad_msg.content = "not json at all"
        bad_choice = MagicMock()
        bad_choice.message = bad_msg
        bad_response.choices = [bad_choice]
        client.chat.completions.create.return_value = bad_response

        judge = VerificationJudge(client, confidence_threshold=0.75)
        finding = judge.judge("fake_b64", "main_menu", "text_contrast_adequate")

        self.assertEqual(finding.confidence, 0.0)
        self.assertTrue(finding.needs_human_review)  # routed to human, not silently failed


class TestComplianceAgentRouting(unittest.TestCase):
    """End-to-end: confirms ComplianceAgent.inspect() runs exact checks
    with zero model calls, and only calls the model for ambiguous checks."""

    def test_exact_checks_run_with_zero_model_calls(self):
        client = MagicMock()
        agent = ComplianceAgent(client, confidence_threshold=0.75)

        # Run with ambiguous_checks_to_run=[] to isolate the exact-only path
        agent.inspect(
            screenshot_b64="fake_b64",
            scene="dialog",
            ui_texts=["Buy 500 Gems", "$4.99"],
            actionable_elements=[{"label": "Buy", "width": 60, "height": 60}],
            is_iap_screen=True,
            ambiguous_checks_to_run=[],
        )

        client.chat.completions.create.assert_not_called()
        self.assertGreater(len(agent.findings_log), 0)

    def test_ambiguous_checks_only_call_model_for_registered_questions(self):
        client = MagicMock()
        client.chat.completions.create.return_value = fake_openai_response(verdict="pass", confidence=0.9)
        agent = ComplianceAgent(client, confidence_threshold=0.75)

        agent.inspect(
            screenshot_b64="fake_b64",
            scene="main_menu",
            ui_texts=["Play"],
            actionable_elements=[],
            ambiguous_checks_to_run=["text_contrast_adequate"],
        )

        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(len(agent.judge_findings_log), 1)

    def test_summary_marks_pending_review_distinct_from_pass(self):
        client = MagicMock()
        client.chat.completions.create.return_value = fake_openai_response(verdict="fail", confidence=0.3)
        agent = ComplianceAgent(client, confidence_threshold=0.75)

        agent.inspect(
            screenshot_b64="fake_b64",
            scene="main_menu",
            ui_texts=["Play"],
            actionable_elements=[],
            ambiguous_checks_to_run=["ad_clearly_labeled"],
        )

        summary = agent.summary()
        self.assertEqual(summary["status"], "PASS_WITH_PENDING_REVIEW")
        self.assertEqual(summary["judge_checks_pending_human_review"], 1)
        self.assertEqual(summary["judge_checks_failed"], 0)  # NOT silently counted as fail


if __name__ == "__main__":
    unittest.main(verbosity=2)
