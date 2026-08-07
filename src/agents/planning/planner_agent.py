"""
agents/planner_agent.py — STAGE 2: PLAN
Turns written requirements (specs.json) into runnable test scenarios
(test_plan.json) that the ExecutorAgent can run, attaching the exact
navigation path the MapAgent discovered to reach each screen.
Two paths:
  deterministic (default): match each spec's target to a mapped screen
    and copy that screen's path. Fully reproducible, no model needed.
  LLM-assisted (USE_LLM=1): expand vague/free-text specs into a
    concrete objective + checks using the configured VLM.
This file also retains the RequirementSpec / TestCase dataclasses used by
the original orchestrator/run_plan flow, so both pipelines are supported.
"""
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import src.core.config as config
from src.models.map_store import MapStore
from src.core.qa_common import ask_llm, _extract_json, log
SPECS_FILE = config.SPECS_FILE
MAP_FILE   = "outputs/results/map_store.json"
PLAN_FILE  = "outputs/results/test_plan.json"
PASSES     = 5
USE_LLM    = os.environ.get("USE_LLM") == "1"

# ---------------------------------------------------------------- DATA CLASSES (original interface)
@dataclass
class TestCase:
    test_id:               str
    title:                 str
    category:             str
    target_screen:        str
    route:                List[Dict[str, Any]]
    check_fn:             str
    check_args:           Dict[str, Any] = field(default_factory=dict)
    requires_ai_judge:    bool = False
    source_requirement_id: str = ""
    generated_at:         float = field(default_factory=time.time)

@dataclass
class RequirementSpec:
    requirement_id:    str
    title:             str
    category:          str
    target_screen:     str
    check_fn:          str
    check_args:        Dict[str, Any] = field(default_factory=dict)
    requires_ai_judge: bool = False

# ---------------------------------------------------------------- MAP LOOKUP
def _find_target_path(mp: dict, spec: dict):
    """Return (nav_path, target_dict, found?) by matching the spec to a mapped screen."""
    nodes = mp.get("nodes", {})
    if spec.get("target_text"):
        want = spec["target_text"].lower()
        for nid, n in nodes.items():
            toks = n.get("tokens") or n.get("sample_ui_texts") or []
            if any(want in t.lower() for t in toks):
                return n.get("path", []), {"text": spec["target_text"]}, True
        for e in mp.get("edges", []):
            edge_lbl = e.get("label") or (e.get("action", {}).get("target") if isinstance(e.get("action"), dict) else "") or ""
            if want in str(edge_lbl).lower():
                from_id = e.get("from") or e.get("from_screen")
                parent = nodes.get(from_id, {})
                return parent.get("path", []) + [edge_lbl], {"text": spec["target_text"]}, True
    if spec.get("target_scene"):
        target_sc = spec["target_scene"]
        cands = []
        for n in nodes.values():
            sc = n.get("scene") or n.get("label")
            if sc == target_sc:
                pth = n.get("path", [])
                cands.append((len(pth), pth))
        if cands:
            cands.sort(key=lambda x: x[0], reverse=True)
            return cands[0][1], {"scene": spec["target_scene"]}, True
    tgt = ({"scene": spec["target_scene"]} if spec.get("target_scene")
           else {"text": spec.get("target_text", "")})
    return [], tgt, False

# ---------------------------------------------------------------- LLM EXPANSION (optional)
def _expand_with_llm(spec: dict, mp: dict) -> Optional[dict]:
    scenes = sorted({n["scene"] for n in mp.get("nodes", {}).values()})
    labels = sorted({e["label"] for e in mp.get("edges", [])})[:30]
    prompt = (
        "You are the Test-plan Generator for an automated game-QA agent.\n"
        "Turn this requirement into a concrete plan. Output ONLY JSON, no prose:\n"
        "{\"objective\": \"<one sentence the decider can act on>\",\n"
        "  \"checks\": [ {\"type\": \"...\", \"...\": \"...\"} ]}\n\n"
        f"Available screens (scenes): {scenes}\n"
        f"Available navigation labels: {labels}\n\n"
        f"Requirement ({spec['category']}): {spec['requirement']}\n"
        f"Existing checks (keep/refine): {json.dumps(spec.get('checks', []))}"
    )
    try:
        return _extract_json(ask_llm(prompt))
    except Exception:
        return None

# ---------------------------------------------------------------- BUILD PLAN
def _default_objective(spec: dict) -> str:
    verb = {"compliance": "Verify", "performance": "Measure",
            "gameplay": "Drive the game to confirm"}
    return f"{verb.get(spec['category'], 'Check')}: {spec['requirement']}"

# ---------------------------------------------------------------- PlannerAgent class
class PlannerAgent:
    """
    Class interface expected by orchestrator.py / run_plan.py.
    Also exposes build_plan() as a standalone entrypoint (called from main.py).
    """
    def __init__(self, game_id: str = None,
                 maps_dir: str = None, plans_dir: str = None):
        from src.core.active_game import GAME as _ACTIVE_GAME
        self.game_id   = game_id or _ACTIVE_GAME.game_id
        self.store     = MapStore(self.game_id, maps_dir=maps_dir or config.MAPS_DIR)
        self.plans_dir = plans_dir or config.PLANS_DIR
    # ---- Original orchestrator interface ----
    def plan(self, requirements: List[RequirementSpec],
             start_screen: str = "main_menu") -> List[TestCase]:
        test_cases, skipped = [], []
        for req in requirements:
            if req.target_screen not in self.store.known_screens():
                skipped.append({"requirement_id": req.requirement_id,
                                 "reason": "MapGap: target screen not mapped"})
                continue
            route_edges = self.store.path_to(req.target_screen, start_screen=start_screen)
            if route_edges is None:
                skipped.append({"requirement_id": req.requirement_id,
                                 "reason": "MapGap: no known route to target"})
                continue
            route = [edge.action for edge in route_edges]
            test_cases.append(TestCase(
                test_id=f"{self.game_id}_{req.requirement_id}",
                title=req.title, category=req.category,
                target_screen=req.target_screen, route=route,
                check_fn=req.check_fn, check_args=req.check_args,
                requires_ai_judge=req.requires_ai_judge,
                source_requirement_id=req.requirement_id,
            ))
        self._save_test_cases(test_cases, skipped)
        return test_cases
    def _save_test_cases(self, test_cases: List[TestCase], skipped: list):
        os.makedirs(self.plans_dir, exist_ok=True)
        path = os.path.join(self.plans_dir, f"{self.game_id}_test_plan.json")
        with open(path, "w") as f:
            json.dump({
                "game_id": self.game_id,
                "generated_at": time.time(),
                "test_cases": [asdict(tc) for tc in test_cases],
                "skipped_requirements": skipped,
            }, f, indent=2)
        try:
            print(f"\U0001f4cb Test plan: {len(test_cases)} cases, "
                  f"{len(skipped)} skipped -> {path}")
        except UnicodeEncodeError:
            print(f"Test plan: {len(test_cases)} cases, "
                  f"{len(skipped)} skipped -> {path}")

    # ---- Standalone entrypoint (called from main.py) ----
    def build_plan(self):
        """
        Build test_plan.json from active game requirements + map_store.json.
        This is the STAGE 2 entrypoint invoked by main.py.
        """
        from src.core.active_game import GAME as _ACTIVE_GAME
        specs = []
        game_name = _ACTIVE_GAME.display_name
        game_id = _ACTIVE_GAME.game_id

        # 1. Prefer active game profile's build_requirements()
        if hasattr(_ACTIVE_GAME, "build_requirements"):
            try:
                reqs = _ACTIVE_GAME.build_requirements()
                for r in reqs:
                    if isinstance(r, RequirementSpec):
                        specs.append({
                            "id": r.requirement_id,
                            "requirement": r.title,
                            "category": r.category,
                            "target_scene": r.target_screen,
                            "checks": [{"type": r.check_fn, **r.check_args}],
                        })
                    elif isinstance(r, dict):
                        specs.append(r)
            except Exception as e:
                log(f"WARNING: _ACTIVE_GAME.build_requirements() failed: {e}")

        # 2. Fall back to active game's specs_file if json exists
        if not specs and os.path.exists(_ACTIVE_GAME.specs_file):
            try:
                data = json.load(open(_ACTIVE_GAME.specs_file))
                specs = data.get("specs", [])
                game_name = data.get("game", game_name)
            except Exception:
                pass

        # 3. Fall back to global SPECS_FILE
        if not specs and os.path.exists(SPECS_FILE):
            data = json.load(open(SPECS_FILE))
            specs = data.get("specs", [])
            game_name = data.get("game", game_name)

        if not specs:
            print(f"ERROR: No requirement specs found for game '{game_name}'.")
            return

        game_map_file = os.path.join(config.MAPS_DIR, f"{game_id}.json")
        if os.path.exists(game_map_file):
            mp = json.load(open(game_map_file))
        elif os.path.exists(MAP_FILE):
            mp_data = json.load(open(MAP_FILE))
            if (mp_data.get("game_id") or mp_data.get("game") or "").lower() in (game_id.lower(), game_name.lower()):
                mp = mp_data
            else:
                mp = {"nodes": {}, "edges": []}
        else:
            print(f"WARNING: No map found for '{game_name}' — run map stage first. "
                  "Scenarios will have empty nav_path / needs_mapping=true.")
            mp = {"nodes": {}, "edges": []}
        created_world = mp.get("created_world") or getattr(_ACTIVE_GAME, "created_world_name", "") or ""
        plan, gaps = [], 0
        for spec in specs:
            nav, target, found = _find_target_path(mp, spec)
            if created_world and spec.get("category") == "gameplay" and target.get("scene") in ("in_game", "pause_menu"):
                # Use navigation path selecting the created world from the Play menu
                nav = ["Play", created_world]
                found = True
            objective = _default_objective(spec)
            checks    = spec.get("checks", [])
            if USE_LLM:
                ex = _expand_with_llm(spec, mp)
                if ex:
                    objective = ex.get("objective", objective)
                    checks    = ex.get("checks", checks) or checks
            scenario = {
                "id":           spec["id"],
                "category":     spec["category"],
                "title":        spec.get("requirement", spec.get("title", "")),
                "objective":    objective,
                "nav_path":     nav,
                "target":       target,
                "checks":       checks,
                "params":       spec.get("params", {}),
                "passes":       PASSES,
                "needs_mapping": not found,
            }
            if not found:
                gaps += 1
            plan.append(scenario)
        out = {"game": game_name, "game_id": game_id, "created_world": created_world, "scenarios": plan}
        json.dump(out, open(PLAN_FILE, "w"), indent=2)
        print(f"\n=== PLAN: {len(plan)} scenarios -> {PLAN_FILE} "
              f"(LLM expansion: {'on' if USE_LLM else 'off'}) ===")
        for s in plan:
            flag = "  !! NEEDS MAPPING" if s["needs_mapping"] else ""
            path_str = " > ".join(s["nav_path"]) or "(reach from root)"
            print(f"  {s['id']:8} {s['category']:11} -> {path_str}{flag}")
        if gaps:
            print(f"\n  {gaps} scenario(s) hit a MapGap. "
                  "Re-run map stage, then re-run plan stage.")