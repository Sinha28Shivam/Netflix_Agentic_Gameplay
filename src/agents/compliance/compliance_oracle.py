"""
ComplianceOracle — the deterministic half of compliance checking.

This is what Q1/Q9/Q14 and the deck's "Compliance Checker (deterministic)"
box actually claim: exact assertions against instrumented facts, not AI
opinion. Everything in this file is a plain rule over data the device
layer already gives us for free (UI text dump, timestamps, known
screen/element state from the map) — no screenshot ever reaches a model
here.

What can and can't live here is the honest line: anything reducible to
"is this exact string present", "did this duration fall in range", or
"is this exact field non-empty" belongs here. Anything that requires
*looking* at the image (contrast, layout crowding, "does this look like
an ad") cannot be a rule and is explicitly routed to VerificationJudge
instead — see compliance_agent.py for the routing logic.

Each check function:
  - takes plain data (ui_texts, timestamps, known elements) — never an image
  - returns a ComplianceFinding with deterministic=True
  - is independently unit-testable with no model, no device, no network
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ComplianceFinding:
    check_id: str
    category: str                  # "content_policy" | "accessibility" | "legal"
    passed: bool
    severity: str                  # "low" | "medium" | "high"
    detail: str
    deterministic: bool = True     # False only for VerificationJudge-sourced findings
    evidence: Dict[str, Any] = field(default_factory=dict)
    scene: str = ""
    timestamp: float = field(default_factory=time.time)


class ComplianceOracle:
    """Exact-rule compliance checks. No model calls. Every method here is
    pure function of plain data in, ComplianceFinding out."""

    # ------------------------------------------------------------------
    # Content policy — exact text/timing assertions
    # ------------------------------------------------------------------
    def assert_iap_modal_shows_price_text(
        self, scene: str, ui_texts: List[str], price_pattern: str = r"[$€£¥]\s?\d"
    ) -> ComplianceFinding:
        """An IAP modal must show an exact price string. This is a text-match
        rule (could be backed by PaddleOCR output in production, ui_texts
        here stands in for that — adb_utils.get_ui_texts already extracts
        on-screen text deterministically via uiautomator, no VLM needed)."""
        import re

        has_price = any(re.search(price_pattern, t) for t in ui_texts)
        return ComplianceFinding(
            check_id="compliance_01_iap_price_disclosure",
            category="content_policy",
            passed=has_price,
            severity="high",
            detail="IAP modal shows an exact price string" if has_price
            else "No price pattern found in on-screen text of an IAP modal",
            evidence={"ui_texts_sample": ui_texts[:10]},
            scene=scene,
        )

    def assert_age_gate_text_present(
        self, scene: str, ui_texts: List[str], required_phrases: Optional[List[str]] = None
    ) -> ComplianceFinding:
        """Age-gating must show one of an exact set of required phrases —
        not 'something age-related', an exact known string the legal team
        approved. This is the kind of check that should NEVER be AI opinion."""
        required_phrases = required_phrases or ["years old", "date of birth", "age rating"]
        joined = " ".join(ui_texts).lower()
        found = [p for p in required_phrases if p.lower() in joined]
        return ComplianceFinding(
            check_id="compliance_02_age_gate_text",
            category="legal",
            passed=bool(found),
            severity="high",
            detail=f"Found required age-gate phrase(s): {found}" if found
            else f"None of the required phrases {required_phrases} found on screen",
            evidence={"matched_phrases": found},
            scene=scene,
        )

    def assert_splash_duration_in_range(
        self, splash_start_ts: float, splash_end_ts: float,
        min_ms: int = 1800, max_ms: int = 2200,
    ) -> ComplianceFinding:
        """Splash/age-rating logo must show for an exact duration window —
        measured from real timestamps the orchestrator already records via
        PerformanceAgent's load-time tracking, not estimated from a frame."""
        duration_ms = (splash_end_ts - splash_start_ts) * 1000
        passed = min_ms <= duration_ms <= max_ms
        return ComplianceFinding(
            check_id="compliance_03_splash_duration",
            category="content_policy",
            passed=passed,
            severity="medium",
            detail=f"Splash shown for {duration_ms:.0f}ms (required {min_ms}-{max_ms}ms)",
            evidence={"duration_ms": round(duration_ms, 1)},
        )

    def assert_no_disallowed_terms_on_screen(
        self, scene: str, ui_texts: List[str], disallowed_terms: List[str]
    ) -> ComplianceFinding:
        """Exact denylist match against on-screen text — e.g. terms that
        violate store policy for the target rating. A rule, not a judgment
        call about 'inappropriateness'."""
        joined = " ".join(ui_texts).lower()
        hits = [term for term in disallowed_terms if term.lower() in joined]
        return ComplianceFinding(
            check_id="compliance_04_disallowed_terms",
            category="content_policy",
            passed=not hits,
            severity="high",
            detail="No disallowed terms found" if not hits else f"Disallowed terms found: {hits}",
            evidence={"hits": hits},
            scene=scene,
        )

    # ------------------------------------------------------------------
    # Accessibility — exact geometric/structural assertions
    # ------------------------------------------------------------------
    def assert_tap_targets_meet_minimum_size(
        self, scene: str, actionable_elements: List[Dict], min_px: int = 48
    ) -> ComplianceFinding:
        """If the Vision Agent (or, on platforms with an accessibility tree,
        a direct UI dump) reports element bounding boxes, this is an exact
        comparison against a known threshold — not a visual 'does this look
        big enough' judgment. Falls back to VerificationJudge (see
        compliance_agent.py routing) only when no bounding-box data exists."""
        undersized = [
            el for el in actionable_elements
            if el.get("width") is not None and el.get("height") is not None
            and (el["width"] < min_px or el["height"] < min_px)
        ]
        return ComplianceFinding(
            check_id="compliance_05_tap_target_size",
            category="accessibility",
            passed=not undersized,
            severity="medium",
            detail="All tap targets meet minimum size" if not undersized
            else f"{len(undersized)} element(s) below {min_px}px minimum",
            evidence={"undersized_labels": [el.get("label") for el in undersized]},
            scene=scene,
        )

    def run_all_exact_checks(
        self,
        scene: str,
        ui_texts: List[str],
        actionable_elements: List[Dict],
        is_iap_screen: bool = False,
        is_age_gate_screen: bool = False,
        disallowed_terms: Optional[List[str]] = None,
    ) -> List[ComplianceFinding]:
        """Run every applicable exact check for the current scene. Returns
        only findings whose rule actually applies here (e.g. IAP price
        check only fires on an IAP screen) — this is what
        ComplianceAgent.inspect() calls before ever considering the judge."""
        findings = []

        if is_iap_screen:
            findings.append(self.assert_iap_modal_shows_price_text(scene, ui_texts))
        if is_age_gate_screen:
            findings.append(self.assert_age_gate_text_present(scene, ui_texts))
        if disallowed_terms:
            findings.append(self.assert_no_disallowed_terms_on_screen(scene, ui_texts, disallowed_terms))

        findings.append(self.assert_tap_targets_meet_minimum_size(scene, actionable_elements))

        return findings
