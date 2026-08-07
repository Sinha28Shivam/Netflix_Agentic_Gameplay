"""
ComplianceAgent — coordinator for compliance checking.

This is the rewrite that closes the gap between the deck's claim
("exact assertions, AI only for ambiguous cases, human triage on
uncertain ones") and what v1 of this file actually did (100% VLM
opinion, no exact rules, no confidence gate, no human queue).

Routing logic, in order, every inspect() call:
  1. Run every ComplianceOracle check that applies to this scene.
     These never see the screenshot. They are exact and reproducible.
  2. For checks that have no rule equivalent (AMBIGUOUS_CHECK_REGISTRY
     in verification_judge.py), call VerificationJudge — but only
     those specific checks, never a free-form "find any compliance
     issues" prompt.
  3. Any judge finding below the confidence threshold is NOT counted
     as a pass or fail in summary() — it's surfaced separately as
     needing human review, matching Q9's "human reviews anything
     uncertain" claim instead of silently resolving it either way.

The screenshot only reaches a model for the four ambiguous checks in
AMBIGUOUS_CHECK_REGISTRY. Everything else — price text, age-gate
phrases, disallowed terms, tap-target pixel size when available — is
decided by ComplianceOracle from on-screen text and element data,
with zero model calls.
"""

from typing import Any, Dict, List, Optional

from src.agents.compliance.compliance_oracle import ComplianceOracle, ComplianceFinding
from src.core.engine.verification_judge import VerificationJudge, AMBIGUOUS_CHECK_REGISTRY


class ComplianceAgent:
    def __init__(self, client, confidence_threshold: float = 0.75):
        self.oracle = ComplianceOracle()
        self.judge = VerificationJudge(client, confidence_threshold=confidence_threshold)
        self.findings_log: List[ComplianceFinding] = []
        self.judge_findings_log = []

    def inspect(
        self,
        screenshot_b64: str,
        scene: str,
        ui_texts: Optional[List[str]] = None,
        actionable_elements: Optional[List[Dict]] = None,
        is_iap_screen: bool = False,
        is_age_gate_screen: bool = False,
        disallowed_terms: Optional[List[str]] = None,
        ambiguous_checks_to_run: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ui_texts = ui_texts or []
        actionable_elements = actionable_elements or []

        # --- Step 1: exact rules, no model call ---
        exact_findings = self.oracle.run_all_exact_checks(
            scene=scene,
            ui_texts=ui_texts,
            actionable_elements=actionable_elements,
            is_iap_screen=is_iap_screen,
            is_age_gate_screen=is_age_gate_screen,
            disallowed_terms=disallowed_terms,
        )
        self.findings_log.extend(exact_findings)

        # --- Step 2: ambiguous checks only, confidence-gated ---
        # Default to the always-applicable visual checks unless the caller
        # explicitly narrows the list. None means "use the default set";
        # [] means "run none" — these must NOT be conflated, or a caller
        # trying to skip the judge entirely would silently still trigger it.
        checks_to_run = (
            list(AMBIGUOUS_CHECK_REGISTRY.keys())
            if ambiguous_checks_to_run is None
            else ambiguous_checks_to_run
        )
        judge_findings = []
        for check_id in checks_to_run:
            finding = self.judge.judge(screenshot_b64, scene, check_id)
            judge_findings.append(finding)
        self.judge_findings_log.extend(judge_findings)

        return {
            "scene": scene,
            "exact_findings": [f for f in exact_findings if not f.passed],
            "judge_findings": [f for f in judge_findings],
            "needs_human_review": [f for f in judge_findings if f.needs_human_review],
        }

    def summary(self) -> Dict[str, Any]:
        exact_fails = [f for f in self.findings_log if not f.passed]
        exact_high = [f for f in exact_fails if f.severity == "high"]

        # A judge finding only counts toward pass/fail if confidence cleared
        # the threshold. Sub-threshold findings are reported separately and
        # do NOT move the status to FAIL or PASS on their own.
        resolved_judge_findings = [f for f in self.judge_findings_log if not f.needs_human_review]
        judge_fails = [f for f in resolved_judge_findings if f.verdict == "fail"]

        pending_review = self.judge.pending_human_review()

        status = "FAIL" if (exact_high or judge_fails) else "PASS"
        if pending_review and status == "PASS":
            status = "PASS_WITH_PENDING_REVIEW"  # honest: not a clean pass while items are queued

        return {
            "status": status,
            "exact_checks_run": len(self.findings_log),
            "exact_checks_failed": len(exact_fails),
            "exact_high_severity_failures": len(exact_high),
            "judge_checks_run": len(self.judge_findings_log),
            "judge_checks_failed": len(judge_fails),
            "judge_checks_pending_human_review": len(pending_review),
            "findings": {
                "exact_failures": [_finding_to_dict(f) for f in exact_fails],
                "judge_failures": [_finding_to_dict(f) for f in judge_fails],
                "pending_human_review": [_finding_to_dict(f) for f in pending_review],
            },
        }


def _finding_to_dict(finding) -> Dict[str, Any]:
    from dataclasses import asdict
    return asdict(finding)
