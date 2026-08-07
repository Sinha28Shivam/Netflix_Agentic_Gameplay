"""
agents/map_agent.py — STAGE 1: MAP (Auto-Mapping agent)

Implements the "Auto-Mapping" from the architecture diagram.

Two distinct modes:
  seed_from_walkthrough()
    Replays a recorded seed (seed_scripts/bloons_seed.json) generically:
    OCR text first, then VLM vlm_locate by description (no hardcoded coordinates).
    Verifies each tap by screen-change. Records screens + transitions.
    Outputs: maps/<game_id>.json (MapStore) AND map_store.json (flat executor copy).

  explore_gaps()
    Runs autonomously after seeding. Finds screens with no recorded outgoing edges
    and probes each actionable element, recording whatever new nodes/edges result.

Both modes reuse VisionAgent (perception) and the qa_common VLM stack (action).
"""

import json
import os
import time
from typing import Dict, List, Optional

import src.core.config as config
from src.models.map_store import MapStore
from src.core.qa_common import (
    log, screencap, save_shot, ocr_all, find_text, clean_tokens,
    vlm_locate, screen_id, screen_signature, wait_for_change, candidate_labels,
    tap, is_loading, clear_popups, solidly_in_match,
    _pixel_hash, _pixel_hash_distance, PIXEL_HASH_CHANGE_THRESHOLD,
)
from src.device.device import force_stop, launch_game, get_current_app, get_screenshot_base64, get_ui_texts

from src.core.active_game import GAME as _ACTIVE_GAME
GAME_NAME    = _ACTIVE_GAME.display_name
GAME_PACKAGE = _ACTIVE_GAME.package
MAP_FILE_FLAT = "outputs/results/map_store.json"          # flat copy for executor / planner

DEFAULT_SEED = []


# ---------------------------------------------------------------- helpers
def _parse_step(raw):
    name = raw.get("name", raw.get("label", "?")) if isinstance(raw, dict) else str(raw)
    if name.upper() == "PLAY":
        return {"name": name, "ocr_label": None,
                "desc": "the large round green PLAY button with a white play triangle "
                        "in the lower-center of the home screen (NOT the 'PLAY SOCIAL' button)"}
    return {"name": name, "ocr_label": name, "desc": f"the '{name}' button or menu item"}


def _settle(*args, **kwargs) -> list:
    """Condition-driven settle: wait until the screen is visually stable, then
    until it's no longer a loading screen. No hardcoded floor or long cap — it
    returns as soon as both conditions hold. (args/kwargs accepted and ignored
    for backward compatibility with old call sites.)"""
    from src.core.qa_common import wait_stable, wait_not_loading, is_loading
    wait_stable()
    toks = wait_not_loading()
    # Extra check if game profile tags it as loading or contains loading keywords
    if is_loading(toks) or (hasattr(_ACTIVE_GAME, "tag_scene") and _ACTIVE_GAME.tag_scene(toks) == "loading"):
        time.sleep(4.0)
        wait_stable()
        toks = wait_not_loading()
    return toks

def _tag_scene(tokens: list, png_path: str = "outputs/logs/current.png") -> str:
    # 1. Let active game profile tag its own scene if implemented
    if hasattr(_ACTIVE_GAME, "tag_scene"):
        try:
            tagged = _ACTIVE_GAME.tag_scene(tokens, png_path)
            if tagged:
                return tagged
        except Exception as e:
            log(f"   _ACTIVE_GAME.tag_scene error: {e}")

    # 2. Check active game's in_game / in_match check
    if hasattr(_ACTIVE_GAME, "is_in_match"):
        try:
            if _ACTIVE_GAME.is_in_match(png_path):
                return "in_game"
        except Exception:
            pass
    elif solidly_in_match(png_path):
        return "in_game"

    blob = " ".join(tokens).lower()
    if any(k in blob for k in ("easy", "medium", "hard")) and "reward" in blob:
        return "difficulty_select"
    if sum(k in blob for k in ("play", "monkeys", "heroes", "powers", "knowledge")) >= 2:
        return "home"
    if any("start" in t.lower() or "welcome" in t.lower() for t in tokens):
        return "title"
    return "menu"


def _record_node(nodes: dict, scene: str, toks: list, path: list, png_path: str = "outputs/logs/current.png") -> str:
    sid = screen_id(scene, toks, png_path)
    if sid not in nodes:
        nodes[sid] = {
            "scene": scene, "tokens": toks, "path": list(path),
            "elements": candidate_labels([{"text": t, "x": 0, "y": 0, "score": 1.0} for t in toks])
        }
    return sid


# ---------------------------------------------------------------- MapAgent class
class MapAgent:
    """
    Wraps the flat map-building logic in the class interface expected by orchestrator.py
    and run_plan.py, while also exposing the standalone build_map() entrypoint.
    """

    def __init__(self, vision_agent=None, executor_agent=None,
                 game_id: str = None, maps_dir: str = None):
        self.vision   = vision_agent
        self.executor = executor_agent
        self.game_id  = game_id or _ACTIVE_GAME.game_id
        self.store    = MapStore(self.game_id, maps_dir=maps_dir or config.MAPS_DIR)

    # ---- Mode 1: guided seed pass (called from run_plan / orchestrator) ----
    def seed_from_walkthrough(self, recorded_actions: Optional[List[Dict]] = None,
                              max_steps: int = 40):
        """Replay recorded_actions (or observe a live human) and record every screen."""
        prev_screen_id = None
        prev_action    = None
        if isinstance(recorded_actions, dict) and "labels" in recorded_actions:
            recorded_actions = [{"action": "tap", "target": label} for label in recorded_actions["labels"]]

        steps = recorded_actions if recorded_actions is not None else [None] * max_steps

        for action in steps:
            state      = self._observe()
            scn_id     = state.get("scene", "unknown")
            self.store.upsert_node(
                screen_id=scn_id,
                ui_texts=state.get("ui_texts", []),
                actionable_elements=state.get("actionable_elements", []),
                is_terminal=scn_id in ("victory", "defeat"),
                tags=["seeded"],
            )
            if prev_screen_id and prev_action:
                self.store.upsert_edge(prev_screen_id, prev_action, scn_id, source="seed")

            if action is None:
                time.sleep(2)
                prev_screen_id, prev_action = scn_id, {"action": "wait", "why": "human-driven seed"}
                continue

            if self.executor:
                self.executor.execute(action, state)
            prev_screen_id, prev_action = scn_id, action
            time.sleep(1.5)

        self.store.save()
        return self.store.coverage_summary()

    # ---- Mode 2: autonomous gap-patching ----
    def explore_gaps(self, max_new_edges: int = 15):
        new_edges = 0
        attempted: set = set()

        for scn_id, node in list(self.store.nodes.items()):
            if new_edges >= max_new_edges:
                break
            tried = {e.action.get("target") for e in self.store.outgoing(scn_id)}
            for element in node.actionable_elements:
                # candidate_labels() (qa_common.py) returns plain OCR-text strings,
                # not {"label": ...} dicts -- normalize both shapes here rather
                # than assuming one, since this crashed on every real map
                # (candidate_labels is what actually populates nodes) and
                # silently forced the much more expensive build_map() fallback
                # every single time instead of this targeted gap-fill.
                target = element.get("label") if isinstance(element, dict) else element
                key = (scn_id, target)
                if not target or target in tried or key in attempted:
                    continue
                attempted.add(key)
                route = self.store.path_to(scn_id)
                if route is None and scn_id != self._current_screen_id():
                    continue
                state = self._observe()
                if state.get("scene") != scn_id:
                    continue
                action = {"action": "tap", "target": target, "why": "auto-mapping gap probe"}
                if self.executor:
                    self.executor.execute(action, state)
                time.sleep(1.5)
                new_state  = self._observe()
                new_scn_id = new_state.get("scene", "unknown")
                self.store.upsert_node(
                    screen_id=new_scn_id,
                    ui_texts=new_state.get("ui_texts", []),
                    actionable_elements=new_state.get("actionable_elements", []),
                    is_terminal=new_scn_id in ("victory", "defeat"),
                )
                self.store.upsert_edge(scn_id, action, new_scn_id, source="explore")
                new_edges += 1

        self.store.save()
        return {"new_edges_found": new_edges, **self.store.coverage_summary()}

    # ---- Standalone entrypoint (called from main.py) ----
    def build_map(self, seed: list = None):
        """
        Walk the seed path generically (OCR + VLM, no hardcoded coordinates),
        building both the MapStore (.json in maps/) and a flat map_store.json.
        """
        if not seed:
            try:
                seed_file = _ACTIVE_GAME.seed_file
            except AttributeError:
                seed_file = config.SEED_FILE

            if os.path.exists(seed_file):
                try:
                    seed = json.load(open(seed_file)).get("labels", [])
                except Exception as e:
                    log(f"   seed file unreadable ({e}); using empty seed")
                    seed = []
            else:
                log(f"   no seed file found at {seed_file}; mapping from fresh launch.")
                seed = []

        names = [s if isinstance(s, str) else s.get("name", "?") for s in seed]
        log(f"=== MAP {GAME_NAME} | model={config.DECIDER_MODEL} | seed: {names} ===")

        force_stop(GAME_PACKAGE)
        launch_game(GAME_PACKAGE)

        nodes, edges, gaps, path = {}, [], [], []
        prev_id = prev_label = None

        i = 0
        while i < len(seed):
            step = _parse_step(seed[i])
            name = step["name"]
            log(f"\n[step {i+1}/{len(seed)}] go to '{name}'")
            toks   = _settle()
            if clear_popups(f"continue toward '{name}'"):
                toks = _settle()
            save_shot(f"map_{name}")
            cur_id = _record_node(nodes, _tag_scene(toks), toks, path)
            if prev_id and prev_id != cur_id:
                edges.append({"from": prev_id, "label": prev_label, "to": cur_id})

            ok = False
            for attempt in range(1, 4):
                if clear_popups(f"continue toward '{name}'"):
                    toks = _settle()
                before = screen_signature()
                pt, method = self._locate(step, attempt)
                if not pt:
                    log(f"   not located (attempt {attempt}); sees {toks[:4]}")
                    time.sleep(2)
                    toks = _settle()
                    continue
                tap(*pt, f"{name}[{method}]")
                if wait_for_change(before, timeout=10):
                    log(f"   '{name}' OK")
                    ok = True
                    break
                log(f"   '{name}' no visible change yet; re-tapping same spot and waiting longer")
                tap(*pt, f"{name}[{method}-retap]")
                if wait_for_change(before, timeout=10):
                    log(f"   '{name}' OK (on retap)")
                    ok = True
                    break
                log(f"   '{name}' no change; retry")
                toks = _settle()

            resume_at = None
            if not ok:
                # Some games resume straight into a mid-session screen on
                # launch (e.g. "continue where you left off") instead of the
                # fresh splash screen the seed script assumes, so the live
                # app can be several steps ahead of where we think we are --
                # not just one. Only checked once the normal attempts above
                # have already failed (not on every step), so the common
                # successful-step case doesn't pay for these extra VLM calls.
                # Check EVERY remaining step, not only the very next one.
                for j in range(i + 1, len(seed)):
                    nxt = _parse_step(seed[j])
                    pt1, _m = self._locate(nxt, 1)
                    pt2, _m = self._locate(nxt, 1) if pt1 else (None, None)
                    if pt1 and pt2:
                        resume_at = j
                        break
                if resume_at is not None:
                    skipped = [_parse_step(seed[k])["name"] for k in range(i, resume_at)]
                    log(f"   {skipped} have no separate buttons on this screen; "
                        f"already past them (step '{_parse_step(seed[resume_at])['name']}' "
                        f"is directly actionable here) — resuming at that step")
                    ok = True
                elif solidly_in_match():
                    log(f"   '{name}' has no separate button on this screen; "
                        f"already reached gameplay without it — skipping")
                    ok = True

            if not ok:
                log(f"   '{name}' NEVER ACTIONABLE — MapGap. OCR saw: {toks[:10]}")
                gaps.append({"from": prev_id, "label": name, "last_seen": toks[:10]})
                break

            if resume_at is not None:
                # This screen turned out to be several steps ahead of `name`
                # -- fold the skipped step names into the path and re-loop at
                # the resumed step instead of treating THIS screen as the
                # result of just the single step `name`. The node for this
                # screen was already recorded above using the OLD (too short)
                # path, before we knew this -- correct it in place, since the
                # executor later relies on this path to actually navigate here
                # from a genuinely fresh launch.
                full_path = path + [_parse_step(seed[k])["name"] for k in range(i, resume_at)]
                nodes[cur_id]["path"] = list(full_path)
                path = full_path
                prev_id    = cur_id
                prev_label = path[-1]
                i = resume_at
                time.sleep(1.5)
                continue

            path       = path + [name]
            prev_id    = cur_id
            prev_label = name
            time.sleep(1.5)
            i += 1

        final = _settle()
        if clear_popups("settle into the screen reached by the golden path"):
            final = _settle()
        # `final` is always a real list (possibly empty) -- `_settle()` never
        # returns None. `if final:` used to gate this on OCR having read at
        # least one token, but an empty list is falsy in Python, so on games
        # where OCR can't read the UI font at all (confirmed true here: every
        # screen in this walk read []), this block silently never ran and the
        # single most important screen -- whatever tapping the last seed step
        # actually landed on, i.e. the live match / in_game screen -- never
        # got recorded. A screenshot always exists at this point regardless
        # of what OCR could read from it, so always record it.
        fscene = _tag_scene(final)
        fid    = _record_node(nodes, fscene, final, path)
        if prev_id and fid != prev_id:
            edges.append({"from": prev_id, "label": prev_label, "to": fid})
        if fscene == "in_game":
            log("   reached gameplay — golden path complete.")

        created_world = getattr(_ACTIVE_GAME, "created_world_name", "") or ""
        out = {"game": GAME_NAME, "package": GAME_PACKAGE,
               "created_world": created_world,
               "root": next(iter(nodes)) if nodes else None,
               "nodes": nodes, "edges": edges, "gaps": gaps}
        json.dump(out, open(MAP_FILE_FLAT, "w"), indent=2)
        log(f"=== done: {len(nodes)} screens, {len(edges)} edges, {len(gaps)} gaps -> {MAP_FILE_FLAT} ===")
        for nid, n in nodes.items():
            log(f"  {nid:28} scene={n['scene']:8} via {' > '.join(n['path']) or '(root)'}")

        # Also persist to MapStore for the agent graph interface.
        # IMPORTANT: `out` above uses the flat schema (from/to/scene/tokens/elements)
        # that's only meant for the executor's flat copy (MAP_FILE_FLAT). It must NOT
        # be json.dump'd as-is into maps/<game_id>.json, because MapStore._load()
        # reconstructs ScreenNode/TransitionEdge dataclasses and expects their exact
        # field names (screen_id/label/... and from_screen/action/to_screen/...).
        # Translate through the public upsert_* API instead, so the file MapStore
        # writes is the one MapStore can also read back.
        for nid, n in nodes.items():
            self.store.upsert_node(
                screen_id=nid,
                label=n.get("scene", nid),
                ui_texts=n.get("tokens", []),
                actionable_elements=n.get("elements", []),
                is_terminal=n.get("scene") in ("victory", "defeat"),
                tags=["seeded"],
            )
        for e in edges:
            self.store.upsert_edge(
                from_screen=e["from"],
                action={"action": "tap", "target": e.get("label")},
                to_screen=e["to"],
                source="seed",
            )
        self.store.save()

    # ---- Internal perception / locator helpers ----
    def _observe(self) -> Dict:
        screenshot_b64 = get_screenshot_base64()
        ui_texts       = get_ui_texts()
        state = {}
        if self.vision:
            state = self.vision.observe(screenshot_b64, ui_texts)
        state["ui_texts"]    = ui_texts
        state["current_app"] = get_current_app()
        return state

    def _current_screen_id(self) -> str:
        return self._observe().get("scene", "unknown")

    @staticmethod
    def _locate(step: dict, attempt: int):
        """OCR-first, VLM fallback."""
        if step.get("ocr_label") and attempt == 1:
            hit = find_text("outputs/logs/current.png", step["ocr_label"])
            if hit:
                return hit, "ocr"
        hit = vlm_locate("outputs/logs/current.png", step["desc"])
        if hit:
            return hit, "vlm"
        if step.get("ocr_label"):
            hit = find_text("outputs/logs/current.png", step["ocr_label"])
            if hit:
                return hit, "ocr-fallback"
        return None, None