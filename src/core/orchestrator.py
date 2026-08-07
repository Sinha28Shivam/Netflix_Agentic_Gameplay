#!/usr/bin/env python3
"""
orchestrator.py — the custom-orchestrated agentic workflow (the "Orchestrator"
box in the architecture diagram: "run agents: sequence & parallel").

It implements the diagram's two phases exactly:

    SETUP  (once per NEW game):   Mapper  ->  Planner
        Skipped automatically if map_store.json + test_plan.json already exist,
        so an already-known game jumps straight to testing. This is the
        "Stages 1-2 once at SETUP" rule.

    TEST CYCLE (every run):
        Executor drives the game (navigate + play)                 [main thread]
        Performance samples FPS/jank/load                          ┐ run in
        Compliance inspects screens (rules + model judgment)       ┘ PARALLEL
        Validator turns the combined evidence into PASS/FAIL/INCONCLUSIVE
        Recovery diagnoses + self-heals and retries on failure  (on failure -> retry)
        Reporter writes results.json (+ HTML report)

"Parallel" is real threading: Performance reads `adb dumpsys` and Compliance
takes its OWN screenshot, so neither collides with the screenshot the gameplay
loop uses. This is a custom workflow (every stage/hand-off is explicit), not a
generic agent framework.
"""

import base64
import json
import os
import threading
import time
from datetime import datetime

import src.core.config as config
from src.core.qa_common import (
    client_ready, log,
    screencap, ocr_all, clean_tokens, find_text, solidly_in_match,
    clear_popups, vlm_locate, screen_signature, wait_for_change,
)
from src.agents.execution.executor_agent import navigate, play, GAME_PACKAGE
from src.agents.compliance.compliance_agent import ComplianceAgent
from src.agents.execution.performance_agent import PerformanceAgent
from src.agents.evaluation.validator_agent import ValidatorAgent
from src.device.device import force_stop, launch_game, back, tap, get_ui_texts

PLAN_FILE     = "outputs/results/test_plan.json"
MAP_FILE      = "outputs/results/map_store.json"
RESULTS_FILE  = "outputs/results/results.json"
COMPLIANCE_PROBE = "outputs/logs/compliance_probe.png"


# ============================================================ SETUP (once)
def _valid_json_file(path: str) -> bool:
    """True only if the file exists, is non-empty, AND parses as JSON. An empty
    or truncated artifact (e.g. from an interrupted map/plan build) must count as
    NOT done -- otherwise setup is silently skipped and the pipeline later crashes
    with a raw JSONDecodeError on load."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        with open(path) as f:
            json.load(f)
        return True
    except (ValueError, OSError):
        return False


def _setup_done() -> bool:
    if not (_valid_json_file(MAP_FILE) and _valid_json_file(PLAN_FILE)):
        return False
    try:
        from src.core.active_game import GAME
        with open(PLAN_FILE) as f:
            plan = json.load(f)
        with open(MAP_FILE) as f:
            map_data = json.load(f)
        plan_game = (plan.get("game_id") or plan.get("game") or "").lower()
        map_game = (map_data.get("game_id") or map_data.get("game") or "").lower()
        active_id = (GAME.game_id or "").lower()
        active_name = (GAME.display_name or "").lower()
        
        # If test_plan or map_store belongs to a DIFFERENT game, setup is NOT done for active game
        if plan_game not in (active_id, active_name) or map_game not in (active_id, active_name):
            log(f"SETUP: detected game switch (current={GAME.display_name}, saved={plan.get('game')}) -> running setup")
            return False
    except Exception:
        return False
    return True


def is_new_game() -> bool:
    return not _setup_done()


def setup(force: bool = False) -> bool:
    """Run Mapper then Planner. Skipped when the game is already mapped+planned,
    so these stages run only once per new game."""
    if _setup_done() and not force:
        log("SETUP: game already mapped & planned -> skipping "
            "(Mapper/Planner run once per new game)")
        return True
    log("=" * 60)
    log("SETUP (new game): Mapper -> Planner")
    from src.agents.planning.map_agent import MapAgent
    from src.agents.planning.planner_agent import PlannerAgent
    MapAgent().build_map()
    if not os.path.exists(MAP_FILE):
        log("SETUP failed: map_store.json not created")
        return False
    PlannerAgent().build_plan()
    if not os.path.exists(PLAN_FILE):
        log("SETUP failed: test_plan.json not created")
        return False
    log("SETUP complete -> map_store.json, test_plan.json")
    return True


# ==================================================== PARALLEL WORKERS
class _PerfWorker(threading.Thread):
    """Performance node — samples device metrics while the Executor plays."""
    def __init__(self, stop_event: threading.Event, interval: int):
        super().__init__(daemon=True)
        self.agent = PerformanceAgent()
        self.stop_event = stop_event
        self.interval = interval

    def run(self):
        while not self.stop_event.is_set():
            try:
                s = self.agent.sample("in_game")
                if s.get("fps") is not None:
                    log(f"    [perf] fps={s['fps']} mem={s.get('memory_mb')}MB cpu={s.get('cpu_pct')}%")
            except Exception as e:
                log(f"    [perf] sample error: {e}")
            self.stop_event.wait(self.interval)


class _ComplianceWorker(threading.Thread):
    """Compliance node — inspects the CURRENT screen (its own screenshot) on an
    interval while the Executor plays. Keeps the latest evidence per spec, so a
    spec is judged on the best screen seen during the cycle. Uses a fresh
    ComplianceAgent per pass so oracle/judge counts never inflate across passes."""
    def __init__(self, comp_specs: list, evidence: dict, lock: threading.Lock,
                 stop_event: threading.Event, interval: int):
        super().__init__(daemon=True)
        self.comp_specs = comp_specs
        self.evidence = evidence
        self.lock = lock
        self.stop_event = stop_event
        self.interval = interval

    def _one_pass(self):
        from src.core.qa_common import client as llm_client
        raw = screencap(COMPLIANCE_PROBE)               # own frame, not current.png
        if not raw:
            return
        b64 = base64.b64encode(raw).decode("utf-8")
        try:
            ui_texts = get_ui_texts()
        except Exception:
            ui_texts = []
        if not ui_texts:
            ui_texts = clean_tokens(ocr_all(COMPLIANCE_PROBE), cap=60)

        for sc in self.comp_specs:
            scene = (sc.get("target", {}) or {}).get("scene") or "unknown"
            title = (sc.get("title") or "").lower()
            is_age = any(k in title for k in ("age", "rating", "splash"))
            is_iap = any(k in title for k in ("purchase", "iap", "price", "buy"))

            element_results, has_timing = [], False
            for chk in sc.get("checks", []):
                if chk.get("type") == "element_present":
                    want = str(chk.get("text", ""))
                    present = (any(want.lower() in t.lower() for t in ui_texts)
                               or bool(find_text(COMPLIANCE_PROBE, want)))
                    element_results.append((want, present))
                elif chk.get("type") == "timing":
                    has_timing = True

            summary = {}
            try:
                comp = ComplianceAgent(llm_client)
                comp.inspect(b64, scene=scene, ui_texts=ui_texts,
                             is_age_gate_screen=is_age, is_iap_screen=is_iap)
                summary = comp.summary()
            except Exception as e:
                log(f"    [compliance] inspect error on {sc['id']}: {e}")
                continue
            with self.lock:
                self.evidence[sc["id"]] = {
                    "scene": scene, "summary": summary, "inspected": True,
                    "element_results": element_results, "has_timing": has_timing,
                }

    def run(self):
        if not self.comp_specs:
            return
        self._one_pass()                                # first pass immediately
        while not self.stop_event.is_set():
            self.stop_event.wait(self.interval)
            if self.stop_event.is_set():
                break
            self._one_pass()


# ==================================================== RECOVERY (self-heal)
HEAL_OCR_BUDGET_S = 5   # give cheap OCR recovery this long before escalating to the VLM


def self_heal(reason: str):
    """Recovery node — diagnose & self-heal, re-select / sweep.

    Escalation ladder (cheap -> smart -> brute force):
      1. OCR (fast/cheap): try to clear a blocking dialog via OCR (clear_popups),
         then a single BACK. Bounded to ~HEAL_OCR_BUDGET_S seconds.
      2. VLM (Claude): if OCR can't resolve the stuck screen in that window,
         ask the vision model to locate a dismiss/close/continue control and tap it.
      3. Sweep: if still stuck, force-stop + relaunch to a known clean state.
    """
    log(f"RECOVERY (self-heal): {reason}")
    screencap("outputs/logs/current.png")
    before = screen_signature("outputs/logs/current.png")
    recovered = False

    # -- Phase 1: OCR (cheap), bounded to ~HEAL_OCR_BUDGET_S --
    deadline = time.time() + HEAL_OCR_BUDGET_S
    tried_back = False
    while time.time() < deadline and not recovered:
        if clear_popups("self-heal: dismiss blocking dialog", max_rounds=1):
            recovered = wait_for_change(before, timeout=2) or True
        elif not tried_back:
            tried_back = True
            log("  [ocr] no recognizable dialog -> BACK")
            back()
            recovered = wait_for_change(before, timeout=2)
        else:
            break   # OCR has nothing else to try
    if recovered:
        log("  recovered via OCR")

    # -- Phase 2: VLM escalation (only if OCR couldn't resolve in time) --
    if not recovered:
        log(f"  [vlm] OCR could not resolve within {HEAL_OCR_BUDGET_S}s -> escalating to Claude (VLM)")
        screencap("outputs/logs/current.png")
        b2 = screen_signature("outputs/logs/current.png")
        spot = vlm_locate(
            "outputs/logs/current.png",
            "a control that closes or dismisses a blocking dialog, popup, or overlay "
            "-- for example an X / Close / OK / Continue / No Thanks / Back button",
        )
        if spot:
            tap(*spot, "VLM self-heal: dismiss overlay")
            recovered = wait_for_change(b2, timeout=4)
            log("  recovered via VLM" if recovered else "  VLM tap did not change the screen")
        else:
            log("  [vlm] no dismiss control located")

    # -- Phase 3: sweep (relaunch) if still stuck --
    if not recovered:
        log("  sweep: force-stop + relaunch to a clean state")
        try:
            force_stop(GAME_PACKAGE)
            time.sleep(2)
            launch_game(GAME_PACKAGE)
            time.sleep(4)
        except Exception as e:
            log(f"  sweep error: {e}")


# ==================================================== ONE TEST CYCLE
def _run_cycle(validator, gameplay_specs, comp_specs, perf_specs) -> list:
    results = []
    started = datetime.now().isoformat()
    interval = int(config.LOOP_SLEEP_SECONDS) + 3

    # Executor needs a real match. Pick the gameplay spec with the deepest
    # navigation / highest target_round as the driver; one play() satisfies all
    # gameplay specs (enter match / cash / round).
    driver = None
    if gameplay_specs:
        cands = [s for s in gameplay_specs if s.get("nav_path")]
        if cands:
            driver = max(cands, key=lambda s: len(s.get("nav_path", [])))
        else:
            driver = gameplay_specs[0]

        # Failsafe: if driver's nav_path is empty, populate from active game's map_seed.json
        if not driver.get("nav_path"):
            from src.core.active_game import GAME as _ACTIVE_GAME
            if hasattr(_ACTIVE_GAME, "seed_file") and os.path.exists(_ACTIVE_GAME.seed_file):
                try:
                    seed_data = json.load(open(_ACTIVE_GAME.seed_file))
                    if isinstance(seed_data, dict) and seed_data.get("labels"):
                        driver["nav_path"] = seed_data["labels"]
                except Exception as e:
                    log(f"   could not load seed_file nav_path: {e}")

    force_stop(GAME_PACKAGE)
    launch_game(GAME_PACKAGE)
    time.sleep(3)

    # --- start Performance ∥ Compliance workers (parallel with the Executor) ---
    stop_event = threading.Event()
    comp_evidence, comp_lock = {}, threading.Lock()
    perf_worker = _PerfWorker(stop_event, interval)
    comp_worker = _ComplianceWorker(comp_specs, comp_evidence, comp_lock, stop_event, interval)
    perf_worker.start()
    comp_worker.start()

    # --- Executor drives the game (main thread) ---
    gp = {"monkeys": 0, "rounds": 0, "target": 0, "reached_match": False, "suite": []}
    session_ok = True
    try:
        if driver:
            target = driver.get("params", {}).get("target_round", 5)
            if driver.get("nav_path"):
                navigate(driver["nav_path"])
            from src.core.active_game import GAME as _ACTIVE_GAME
            if getattr(_ACTIVE_GAME, "genre", None) == "runner":
                # Real-time runner: the game's play() drives capture+CV+swipe itself.
                result = _ACTIVE_GAME.play()
                gp = {"monkeys": 0, "rounds": 0, "target": target,
                      "reached_match": True, "suite": [],
                      "runner": (getattr(result, "notes", None) or {})}
            else:
                # Turn-based path (Bloons / Minecraft)
                play_res = play(target_round=target)
                if isinstance(play_res, tuple) and len(play_res) == 3:
                    monkeys, rounds, suite = play_res
                    reached = solid_match = solidly_in_match()
                elif hasattr(play_res, "suite_ran"):
                    monkeys, rounds = 0, 0
                    suite = play_res.notes.get("suite") if isinstance(play_res.notes, dict) else []
                    reached = bool(play_res.suite_ran or suite)
                else:
                    monkeys, rounds, suite = 0, 0, []
                    reached = False
                gp = {"monkeys": monkeys, "rounds": rounds, "target": target,
                      "reached_match": reached, "suite": suite}
        else:
            log(" no gameplay spec; running a perf/compliance-only cycle")
            time.sleep(int(config.LOOP_SLEEP_SECONDS) * 6)
    except Exception as e:
        session_ok = False
        log(f" cycle error during play: {e}")
    finally:
        stop_event.set()
        perf_worker.join(timeout=10)
        comp_worker.join(timeout=15)

    perf_summary = perf_worker.agent.summary()

    # --- Validator: combined evidence -> per-spec verdicts ---
    for sc in gameplay_specs:
        results.append(_stamp(validator.gameplay(sc, gp), started))
    for sc in perf_specs:
        results.append(_stamp(validator.performance(sc, perf_summary, session_ok), started))
    for sc in comp_specs:
        with comp_lock:
            ev = comp_evidence.get(sc["id"])
        if ev is None:
            ev = {"inspected": False, "scene": (sc.get("target", {}) or {}).get("scene", "unknown")}
        results.append(_stamp(validator.compliance(sc, ev), started))
    return results


def _stamp(result: dict, start_iso: str) -> dict:
    result.setdefault("start_time", start_iso)
    result["end_time"] = datetime.now().isoformat()
    return result


# ==================================================== EXECUTE + REPORT
def run_cycle_and_report(write_report: bool = False, allow_relearn: bool = True) -> bool:
    """Load the plan, run the parallel test cycle with Recovery retries, write
    results.json (and optionally the HTML report). This is what main.py's
    --execute stage / executor_agent.execute_all() delegate to."""
    if not client_ready():
        print("ERROR: LLM client not configured (check API key env var).")
        return False
    if not _valid_json_file(PLAN_FILE):
        print(f"ERROR: {PLAN_FILE} is missing or not valid JSON (empty/corrupt). "
              f"Regenerate it with `python main.py --force-setup`.")
        return False

    plan = json.load(open(PLAN_FILE))
    scenarios = plan.get("scenarios", [])

    def _keep(sc):  # compliance inspects the current screen -> map-gaps don't block it
        return not (sc.get("needs_mapping") and sc.get("category") != "compliance")

    gameplay_specs = [s for s in scenarios if s["category"] == "gameplay" and _keep(s)]
    comp_specs     = [s for s in scenarios if s["category"] == "compliance" and _keep(s)]
    perf_specs     = [s for s in scenarios if s["category"] == "performance" and _keep(s)]

    log(f"ORCHESTRATOR | {plan.get('game','?')} | model={config.DECIDER_MODEL} | "
        f"gameplay={len(gameplay_specs)} compliance={len(comp_specs)} perf={len(perf_specs)}")

    validator = ValidatorAgent()
    max_attempts = 1 if not allow_relearn else max(1, int(config.MAX_RECOVERY_ATTEMPTS))
    results = []
    for attempt in range(1, max_attempts + 1):
        log("=" * 60)
        log(f"TEST CYCLE attempt {attempt}/{max_attempts}")
        results = _run_cycle(validator, gameplay_specs, comp_specs, perf_specs)

        # Recovery retries only when a GAMEPLAY spec failed -- a relaunch can fix
        # the Executor getting stuck; perf/compliance verdicts are evidence-based
        # and won't change on a blind retry.
        gameplay_failed = any(r["category"] == "gameplay" and r["verdict"] in ("FAIL", "ERROR")
                              for r in results)
        if not gameplay_failed or attempt >= max_attempts:
            if attempt > 1:
                for r in results:
                    r["logs"].append(f"(cycle attempt {attempt})")
            break
        self_heal(f"gameplay failed on attempt {attempt}")

    # ---- Continuous Learning Loop (Option B: continue -> record gaps ->
    #      re-map + replan AFTER the cycle -> re-run ONLY resolved gaps once) ----
    if allow_relearn:
        results = _relearn_on_gaps(validator, scenarios, results)

    json.dump(results, open(RESULTS_FILE, "w"), indent=2)
    _log_summary(results)

    if write_report:
        try:
            from src.agents.evaluation.report_agent import generate_report
            path = generate_report()
            if path:
                log(f"REPORT -> {path}")
        except Exception as e:
            log(f"report error: {e}")
    return True


def _relearn_on_gaps(validator, scenarios, results):
    """Option B learning loop. If the plan has mapping gaps, extend the map and
    replan ONCE, then re-run only the scenarios the re-map actually resolved and
    merge their fresh results in. Never loops more than once (no re-map storms)."""
    gap_ids = [s["id"] for s in scenarios if s.get("needs_mapping")]
    if not gap_ids:
        return results

    log("=" * 60)
    log(f"LEARNING LOOP: {len(gap_ids)} mapping gap(s) {gap_ids} -> re-map + replan")
    try:
        from src.agents.planning.map_agent import MapAgent
        from src.agents.planning.planner_agent import PlannerAgent
        mapper = MapAgent()
        try:
            mapper.explore_gaps()        # targeted map extension (cheaper than a full re-map)
        except Exception as e:
            log(f"  explore_gaps unavailable, rebuilding map: {e}")
            mapper.build_map()
        PlannerAgent().build_plan()      # replan against the extended map
    except Exception as e:
        log(f"  re-map/replan error: {e}; leaving gaps as-is")
        return results

    new_scen = json.load(open(PLAN_FILE)).get("scenarios", [])
    resolved = [s for s in new_scen if s["id"] in gap_ids and not s.get("needs_mapping")]
    if not resolved:
        log("  re-map did not resolve the gap(s); leaving them as-is (no re-loop)")
        return results

    log(f"  {len(resolved)} gap(s) now routable -> re-running only those: "
        f"{[s['id'] for s in resolved]}")
    gp2 = [s for s in resolved if s["category"] == "gameplay"]
    cp2 = [s for s in resolved if s["category"] == "compliance"]
    pf2 = [s for s in resolved if s["category"] == "performance"]
    gap_results = _run_cycle(validator, gp2, cp2, pf2)

    # Merge: replace the gap scenarios' results, preserving original order.
    fresh = {r["id"]: r for r in gap_results}
    merged = [fresh.get(r["id"], r) for r in results]
    known = {x["id"] for x in merged}
    for r in gap_results:            # include any gap ids not already in results
        if r["id"] not in known:
            merged.append(r)
    return merged


def _log_summary(results):
    def n(v): return sum(1 for r in results if r["verdict"] == v)
    log(f"DONE -> {RESULTS_FILE} | PASS {n('PASS')} | PARTIAL {n('PARTIAL')} | "
        f"FAIL {n('FAIL')} | INCONCLUSIVE {n('INCONCLUSIVE')} | ERROR {n('ERROR')}")


# ==================================================== TOP-LEVEL ENTRY
def run(force_setup: bool = False) -> bool:
    """Full run: setup (only if new game) -> parallel test cycle + recovery ->
    report. This is the default entrypoint from main.py."""
    if not setup(force=force_setup):
        print("Setup failed; aborting.")
        return False
    return run_cycle_and_report(write_report=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Agentic Game QA — Orchestrator")
    ap.add_argument("--force-setup", action="store_true",
                    help="Re-run Mapper+Planner even if the game is already mapped")
    args = ap.parse_args()
    run(force_setup=args.force_setup)
