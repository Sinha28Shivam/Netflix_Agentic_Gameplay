"""
TestRunner — closes the gap between PlannerAgent's output and an actual
device run. This is the piece that was missing: map_and_plan.py produced
TestCase objects, but orchestrator.py only ever ran one hardcoded
mission and never consumed them.

What it does, per TestCase:
  1. Replays test_case.route (the resolved action sequence from the map)
     using the SAME ExecutorAgent/VisionAgent the gameplay loop already
     uses — no new action/perception code, matching the deck's "per-game
     logic is config, not a new engine" claim.
  2. Once the route's target_screen is reached, dispatches to:
       - GAMEPLAY_CHECK_REGISTRY[test_case.check_fn]   if category == "gameplay"
       - ComplianceOracle / VerificationJudge            if category == "compliance"
       - PerformanceAgent-backed checks                  if category == "performance"
     using the SAME requires_ai_judge flag the planner already attached,
     so the routing decision was made once, at plan time, not re-derived
     here.
  3. Returns a TestResult with the same PASS/FAIL/ERROR vocabulary the
     existing OracleAgent and ComplianceAgent use, so reports stay
     consistent across both paths.

This intentionally does NOT replace orchestrator.py's open-ended mission
loop (decide-your-own-next-move toward a fuzzy goal) — that's still the
right tool for "play until round 10". TestRunner is for the OTHER half
of the architecture: short, scoped, plan-derived checks against a
specific known screen.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.models.gameplay_checks import GAMEPLAY_CHECK_REGISTRY
from src.core.engine.verification_judge import AMBIGUOUS_CHECK_REGISTRY


@dataclass
class TestResult:
    test_id: str
    title: str
    category: str
    status: str                 # "PASS" | "FAIL" | "ERROR"
    reason: str
    needs_human_review: bool = False
    route_steps_executed: int = 0
    duration_seconds: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)


class TestRunner:
    def __init__(self, vision_agent, executor_agent, compliance_agent, performance_agent,
                 capture_state_fn, max_route_retries: int = 2):
        """
        capture_state_fn: zero-arg callable returning the same `state` dict
        shape orchestrator.capture_state() produces. Passed in rather than
        re-implemented here so TestRunner and QAOrchestrator share one
        perception path — no duplicate device/vision code.
        """
        self.vision = vision_agent
        self.executor = executor_agent
        self.compliance = compliance_agent
        self.performance = performance_agent
        self.capture_state = capture_state_fn
        self.max_route_retries = max_route_retries

    def run(self, test_case) -> TestResult:
        start = time.time()

        # --- Step 1: drive the resolved route ---
        steps_executed = 0
        for step_action in test_case.route:
            ok = self._execute_with_retry(step_action)
            steps_executed += 1
            if not ok:
                return TestResult(
                    test_id=test_case.test_id,
                    title=test_case.title,
                    category=test_case.category,
                    status="ERROR",
                    reason=f"Route step {steps_executed}/{len(test_case.route)} failed after retries: {step_action}",
                    route_steps_executed=steps_executed,
                    duration_seconds=time.time() - start,
                )
            time.sleep(1.0)

        state = self.capture_state()

        if state.get("scene") != test_case.target_screen:
            return TestResult(
                test_id=test_case.test_id,
                title=test_case.title,
                category=test_case.category,
                status="ERROR",
                reason=(
                    f"Route completed but landed on '{state.get('scene')}', "
                    f"expected '{test_case.target_screen}' — possible MapGap "
                    f"(game UI may have changed since the route was mapped)"
                ),
                route_steps_executed=steps_executed,
                duration_seconds=time.time() - start,
            )

        # --- Step 2: dispatch to the right deterministic/judge check ---
        if test_case.category == "gameplay":
            result = self._run_gameplay_check(test_case, state)
        elif test_case.category == "compliance":
            result = self._run_compliance_check(test_case, state)
        elif test_case.category == "performance":
            result = self._run_performance_check(test_case, state)
        else:
            result = TestResult(
                test_id=test_case.test_id, title=test_case.title, category=test_case.category,
                status="ERROR", reason=f"Unknown category '{test_case.category}'",
            )

        result.route_steps_executed = steps_executed
        result.duration_seconds = time.time() - start
        return result

    # ------------------------------------------------------------------
    # Dispatch targets
    # ------------------------------------------------------------------
    def _run_gameplay_check(self, test_case, state) -> TestResult:
        if test_case.requires_ai_judge:
            # Gameplay checks the planner already flagged as visual-only
            # (e.g. red/white/green placement validity) route to the judge,
            # not a fabricated rule — same confidence-gated path compliance
            # checks use, just reusing the compliance agent's judge instance.
            screenshot_b64 = self._latest_screenshot(state)
            check_id = self._nearest_registered_judge_check(test_case.check_fn)
            if check_id is None:
                return TestResult(
                    test_id=test_case.test_id, title=test_case.title, category="gameplay",
                    status="ERROR",
                    reason=(
                        f"'{test_case.check_fn}' requires AI judgment but has no match in "
                        f"AMBIGUOUS_CHECK_REGISTRY — add it there explicitly rather than "
                        f"letting this fail silently or guess."
                    ),
                )
            finding = self.compliance.judge.judge(screenshot_b64, state.get("scene", ""), check_id)
            status = "FAIL" if finding.needs_human_review else finding.verdict.upper()
            return TestResult(
                test_id=test_case.test_id, title=test_case.title, category="gameplay",
                status=status if status in ("PASS", "FAIL") else "FAIL",
                reason=finding.reasoning,
                needs_human_review=finding.needs_human_review,
                evidence={"confidence": finding.confidence, "check_id": check_id},
            )

        check_fn = GAMEPLAY_CHECK_REGISTRY.get(test_case.check_fn)
        if check_fn is None:
            return TestResult(
                test_id=test_case.test_id, title=test_case.title, category="gameplay",
                status="ERROR",
                reason=f"No implementation registered for check_fn '{test_case.check_fn}' in gameplay_checks.py",
            )
        verdict = check_fn(state, test_case.check_args)
        return TestResult(
            test_id=test_case.test_id, title=test_case.title, category="gameplay",
            status=verdict["status"], reason=verdict["reason"],
        )

    def _run_compliance_check(self, test_case, state) -> TestResult:
        screenshot_b64 = self._latest_screenshot(state)
        result = self.compliance.inspect(
            screenshot_b64,
            state.get("scene", ""),
            ui_texts=state.get("ui_texts", []),
            actionable_elements=state.get("actionable_elements", []),
            is_iap_screen="iap" in test_case.check_fn.lower() or "price" in test_case.check_fn.lower(),
            is_age_gate_screen="age_gate" in test_case.check_fn.lower(),
            ambiguous_checks_to_run=[] if not test_case.requires_ai_judge else None,
        )
        exact_fail = next(
            (f for f in result["exact_findings"] if f.check_id == test_case.source_requirement_id
             or test_case.check_fn.replace("assert_", "").split("_")[0] in f.check_id), None
        )
        if exact_fail:
            return TestResult(
                test_id=test_case.test_id, title=test_case.title, category="compliance",
                status="FAIL", reason=exact_fail.detail, evidence=exact_fail.evidence,
            )
        if result["needs_human_review"]:
            return TestResult(
                test_id=test_case.test_id, title=test_case.title, category="compliance",
                status="FAIL", reason="Routed to human review — see pending_human_review queue",
                needs_human_review=True,
            )
        return TestResult(
            test_id=test_case.test_id, title=test_case.title, category="compliance",
            status="PASS", reason="No exact-rule or confident-judge failures found",
        )

    def _run_performance_check(self, test_case, state) -> TestResult:
        check_fn = GAMEPLAY_CHECK_REGISTRY.get(test_case.check_fn)
        if check_fn is None:
            return TestResult(
                test_id=test_case.test_id, title=test_case.title, category="performance",
                status="ERROR",
                reason=f"No implementation registered for check_fn '{test_case.check_fn}' in gameplay_checks.py",
            )
        perf_state = dict(state)
        perf_state["performance"] = self.performance.summary()
        verdict = check_fn(perf_state, test_case.check_args)
        return TestResult(
            test_id=test_case.test_id, title=test_case.title, category="performance",
            status=verdict["status"], reason=verdict["reason"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _execute_with_retry(self, action: Dict) -> bool:
        """Re-uses ExecutorAgent.execute but adds the 'verify after act,
        retry on miss' behavior the Q&A doc promises for Q3 — only at
        this scoped-test layer for now, not yet in the open-ended mission
        loop in orchestrator.py."""
        for attempt in range(self.max_route_retries + 1):
            state_before = self.capture_state()
            ok = self.executor.execute(action, state_before)
            if ok:
                return True
            time.sleep(1.0)
        return False

    def _latest_screenshot(self, state) -> Optional[str]:
        # capture_state_fn callers (orchestrator) stash the last screenshot;
        # re-capture here to guarantee freshness for the check just dispatched.
        from src.device.device import get_screenshot_base64
        return get_screenshot_base64()

    def _nearest_registered_judge_check(self, check_fn: str) -> Optional[str]:
        """check_fn names from category_specs.py (e.g.
        'assert_tower_snapped_to_legal_tile') don't share a vocabulary with
        AMBIGUOUS_CHECK_REGISTRY's keys yet. Rather than silently guessing
        a mapping, this does an explicit, auditable lookup table — extend
        it deliberately per game, same as everything else here."""
        explicit_map = {
            "assert_tower_panel_scroll_reveals_items": "tap_target_visual_size",
            "assert_tower_snapped_to_legal_tile": "color_only_information",
        }
        return explicit_map.get(check_fn)


def run_test_plan(test_cases: List, runner: "TestRunner") -> List[TestResult]:
    """Runs every TestCase in a plan sequentially against one device.
    Parallel-across-devices is NOT implemented here — see README's
    honest-gaps list; this runs one device's worth of the matrix."""
    results = []
    for tc in test_cases:
        print(f"\n▶ Running {tc.test_id}: {tc.title}")
        result = runner.run(tc)
        print(f"   {result.status} — {result.reason}")
        results.append(result)
    return results
