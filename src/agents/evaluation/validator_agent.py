"""
agents/validator_agent.py — the Validator / Evaluator node ("4. Evaluator").

Runs AFTER the Executor (gameplay), Performance sampler, and Compliance
inspector have produced raw evidence for one test cycle. Its only job is
judgment: turn that evidence into a per-spec verdict (PASS / FAIL / PARTIAL /
INCONCLUSIVE) plus written evidence lines.

No device and no model dependency — pure evaluation of collected facts. That
keeps "drive the game" (Executor), "measure" (Performance), "inspect"
(Compliance) and "decide pass/fail" (Validator) as separate, independently
testable responsibilities, exactly as the architecture separates them.
"""

from typing import Any, Dict


class ValidatorAgent:
    # ---- gameplay -------------------------------------------------------
    def gameplay(self, spec: dict, ev: Dict[str, Any]) -> Dict[str, Any]:
        """ev = {monkeys, rounds, target, reached_match, suite:[(name,status,detail)]}."""
        checks = spec.get("checks", [{}])
        ctype = checks[0].get("type") if checks else None
        monkeys = ev.get("monkeys", 0)
        rounds = ev.get("rounds", 0)
        target = ev.get("target", spec.get("params", {}).get("target_round", 5))
        reached = ev.get("reached_match", False) or monkeys > 0 or rounds > 0
        logs = []

        if not reached:
            return self._mk(spec, "FAIL", ev, ["never reached a live match"])

        # Match individual scenario results from suite if present for this spec
        spec_id = str(spec.get("id", "")).lower()
        spec_title = str(spec.get("title", "")).lower()
        matched_result = None

        for n, s, d in ev.get("suite", []):
            n_clean = n.lower()
            if ("mc_07" in spec_id or "mc1" in spec_id or "joystick" in spec_title) and "mc1" in n_clean:
                matched_result = (n, s, d)
            elif ("mc_08" in spec_id or "mc2" in spec_id or "camera" in spec_title or "look" in spec_title) and "mc2" in n_clean:
                matched_result = (n, s, d)
            elif ("mc_09" in spec_id or "mc3" in spec_id or "hotbar" in spec_title) and "mc3" in n_clean:
                matched_result = (n, s, d)
            elif ("mc_10" in spec_id or "mc4" in spec_id or "block" in spec_title) and "mc4" in n_clean:
                matched_result = (n, s, d)
            elif ("mc_11" in spec_id or "mc5" in spec_id or "pause" in spec_title) and "mc5" in n_clean:
                matched_result = (n, s, d)
            elif ("mc_12" in spec_id or "mc6" in spec_id or "save" in spec_title) and "mc6" in n_clean:
                matched_result = (n, s, d)
            elif ("mc7" in spec_id or "autonomous" in spec_title) and "mc7" in n_clean:
                matched_result = (n, s, d)

        if matched_result:
            n, s, d = matched_result
            verdict = s  # Directly use "PASS" or "FAIL" from scenario result
            logs.append(f"[{s}] {n}" + (f" - {d}" if d else ""))
        elif reached:
            verdict = "PASS"
            logs.append("reached live match and completed gameplay steps")
        else:
            verdict = "FAIL"
            for n, s, d in ev.get("suite", []):
                logs.append(f"[{s}] {n}" + (f" - {d}" if d else ""))

        return self._mk(spec, verdict, ev, logs)

    @staticmethod
    def _apply_suite(verdict, ev, logs):
        fails = [n for n, s, _ in ev.get("suite", []) if s == "FAIL"]
        if fails and verdict == "PASS":
            logs.append(f"in-match check(s) failed: {', '.join(fails)}")
            return "PARTIAL"
        return verdict

    # ---- performance ----------------------------------------------------
    def performance(self, spec: dict, summary: Dict[str, Any], session_ok: bool) -> Dict[str, Any]:
        """summary = PerformanceAgent.summary(); session_ok = play() completed without the app dying."""
        checks = spec.get("checks", [{}])
        ctype = checks[0].get("type") if checks else None
        avg_fps = summary.get("avg_fps")
        logs = list(summary.get("issues", []))

        if ctype == "no_crash":                # PERF-02
            verdict = "PASS" if session_ok else "FAIL"
            logs.append("session completed without app exit" if session_ok
                        else "app left foreground / session did not complete")
        else:                                  # PERF-01 (fps) and generic perf
            if avg_fps is None:
                verdict = "INCONCLUSIVE"
                logs.append("no usable fps samples (device/gfxinfo unavailable?)")
            else:
                verdict = "FAIL" if summary.get("status") == "FAIL" else "PASS"
        metrics = {"avg_fps": avg_fps, "peak_memory_mb": summary.get("peak_memory_mb"),
                   "samples": len(summary.get("samples", []))}
        return self._wrap(spec, verdict, metrics, logs)

    # ---- compliance -----------------------------------------------------
    def compliance(self, spec: dict, ev: Dict[str, Any]) -> Dict[str, Any]:
        """ev = {summary(dict), element_results:[(text,present)], has_timing:bool, inspected:bool, scene}."""
        summary = ev.get("summary", {}) or {}
        logs = []
        verdict = "PASS"

        if not ev.get("inspected"):
            return self._wrap(spec, "INCONCLUSIVE",
                              {"scene": ev.get("scene", "unknown")},
                              ["compliance not inspected on a matching screen this cycle "
                               "(needs its own navigation target)"])

        for text, present in ev.get("element_results", []):
            logs.append(f"[{'PASS' if present else 'FAIL'}] element_present '{text}'")
            if not present:
                verdict = "FAIL"

        if ev.get("has_timing"):
            logs.append("[PENDING] timing check needs splash-timing instrumentation "
                        "(not measurable from a single frame)")
            if verdict == "PASS":
                verdict = "PARTIAL"

        if summary:
            if summary.get("status") == "FAIL":
                verdict = "FAIL"
            elif summary.get("status") == "PASS_WITH_PENDING_REVIEW" and verdict == "PASS":
                verdict = "PARTIAL"
            logs.append(
                f"oracle {summary.get('exact_checks_run',0)} run/"
                f"{summary.get('exact_checks_failed',0)} failed; "
                f"judge {summary.get('judge_checks_run',0)} run/"
                f"{summary.get('judge_checks_failed',0)} failed/"
                f"{summary.get('judge_checks_pending_human_review',0)} pending review"
            )
        metrics = {
            "scene": ev.get("scene", "unknown"),
            "exact_failed": summary.get("exact_checks_failed", 0),
            "pending_review": summary.get("judge_checks_pending_human_review", 0),
        }
        return self._wrap(spec, verdict, metrics, logs)

    # ---- helpers --------------------------------------------------------
    def _mk(self, spec, verdict, ev, logs):
        metrics = {"monkeys_placed": ev.get("monkeys", 0),
                   "rounds_reached": ev.get("rounds", 0),
                   "target": ev.get("target")}
        return self._wrap(spec, verdict, metrics, logs)

    @staticmethod
    def _wrap(spec, verdict, metrics, logs):
        return {
            "id": spec["id"],
            "category": spec["category"],
            "title": spec.get("title", spec.get("requirement", spec["id"])),
            "verdict": verdict,
            "metrics": metrics,
            "logs": logs,
        }
