"""
agents/executor_agent.py — STAGE 3: EXECUTE

Generic, VLM-driven, self-verifying test executor.

No hardcoded coordinates. For every action the VLM is asked WHERE the element
is (vlm_locate), we tap, then VERIFY it worked:
  - navigation: the screen's word-set changed
  - placing a monkey: cash went down
  - starting a round: the round counter advanced

Everything is logged to ./logs with a screenshot at each step.

Also retains the original ExecutorAgent class interface so orchestrator.py
and run_plan.py continue to work unchanged.
"""

import json
import os
import time
from datetime import datetime

import src.core.config as config
import src.core.qa_common as qac
from src.models import scenarios
from src.core.qa_common import (
    log, screencap, save_shot, screen_signature, wait_for_change,
    vlm_locate, vlm_locate_precise, find_text, clean_tokens, ocr_all, read_hud,
    is_loading, clear_popups, solidly_in_match, in_match, record,
    results_summary, _pixel_hash, _pixel_hash_distance, PIXEL_HASH_CHANGE_THRESHOLD,
)
from src.models.gameplay_descriptions import (
    DART_DESC, GRASS_DESC, GRASS_FALLBACK, GREEN_DESC, FF_DESC, CONFIRM_PLAY_DESC,
    BOMB_DESC, ICE_DESC, TACK_DESC,
)

# Varied deployment roster: (name, VLM description, approx cost). Rotated through
# by the economy loop for tower variety; costs are approximate (the actual buy is
# verified by the cash drop), and any tower we can't afford / can't find falls back
# to the cheapest Dart Monkey. Keep the Dart Monkey first (the guaranteed fallback).
TOWER_ROSTER = [
    ("Dart Monkey", DART_DESC, config.DART_COST),
    ("Tack Shooter", TACK_DESC, 280),
    ("Bomb Shooter", BOMB_DESC, 350),
    ("Ice Monkey", ICE_DESC, 340),
]
from src.device.device import tap, back, swipe, drag, force_stop, launch_game
from src.core.active_game import GAME as ACTIVE_GAME, active_package

PLAN_FILE    = "outputs/results/test_plan.json"
RESULTS_FILE = "outputs/results/results.json"
GAME_PACKAGE = active_package()

# TD economy constants, sourced from the active game (falls back to config for a
# non-tower-defense game that doesn't define them). Moves fully into
# TowerDefenseMixin in Phase 3.
_CHEAPEST_UNIT = getattr(ACTIVE_GAME, "cheapest_unit_cost", config.DART_COST)
_CASH_RESERVE  = getattr(ACTIVE_GAME, "cash_reserve", config.CASH_RESERVE)
_MAX_UNITS     = getattr(ACTIVE_GAME, "max_units", config.MAX_MONKEYS)


# ================================================================
# Original ExecutorAgent class (used by orchestrator.py / run_plan.py)
# ================================================================
class ExecutorAgent:
    """Minimal action-dispatch executor for the orchestrator loop."""

    def find_element(self, state: dict, target: str):
        for element in state.get("actionable_elements", []):
            if element.get("label", "").lower() == (target or "").lower():
                return element
        return None

    def tap_target(self, state: dict, target: str) -> bool:
        element = self.find_element(state, target)
        if element is None:
            print(f"❌ Cannot find target: {target}")
            return False
        print(f"👆 Tapping {target} at ({element['x']}, {element['y']})")
        tap(element["x"], element["y"])
        return True

    def execute(self, decision: dict, state: dict) -> bool:
        action = decision.get("action")
        if action == "tap":
            return self.tap_target(state, decision.get("target"))
        if action == "wait":
            ms = decision.get("ms", 2000)
            print(f"⏳ Waiting {ms} ms")
            time.sleep(ms / 1000)
            return True
        if action == "swipe_left":
            from src.device.device import swipe_left; swipe_left(); return True
        if action == "swipe_right":
            from src.device.device import swipe_right; swipe_right(); return True
        if action == "swipe_up":
            from src.device.device import swipe_up; swipe_up(); return True
        if action == "swipe_down":
            from src.device.device import swipe_down; swipe_down(); return True
        if action == "done":
            print(f"✅ Mission step complete: {decision.get('result', 'done')}")
            return True
        print(f"❓ Unknown action: {action}")
        return False


# ================================================================
# Stage-3 executor: navigate + play + run full test plan
# ================================================================

# -- helpers ---------------------------------------------------------
def _settle(timeout: int = 25, settle_reads: int = 2, min_wait: float = 8.0, max_loading_wait: float = 90.0) -> list:
    """Wait past any 'loading...' screen, then keep reading until the screen
    settles, using the same approach as agents/map_agent.py's _settle() (see
    that file for the full rationale). This function used to be its own
    unfixed copy -- it required an EXACT OCR token-set match twice in a row
    to consider the screen stable, and gave a loading screen only one extra
    3s grace period. On BTD6's animated menus and its ~10-tip loading
    sequence, that meant this copy could return (and let callers like play()
    check solidly_in_match()) on a screen that hadn't actually finished
    rendering yet -- while the map_agent.py copy, which HAD been fixed, did
    not have this problem. Same navigation, same screens, different (buggy)
    outcome was traced to exactly this duplicated-and-diverged function.
    """
    start = time.time()
    deadline = start + timeout
    last_hash, stable = None, 0
    while time.time() < deadline:
        screencap("outputs/logs/current.png")
        cur_hash = _pixel_hash("outputs/logs/current.png")
        if last_hash is not None and _pixel_hash_distance(last_hash, cur_hash) < PIXEL_HASH_CHANGE_THRESHOLD:
            stable += 1
        else:
            stable = 1
        last_hash = cur_hash
        if stable >= settle_reads and (time.time() - start) >= min_wait:
            break
        time.sleep(1.0)

    loading_deadline = time.time() + max_loading_wait
    toks = clean_tokens(ocr_all("outputs/logs/current.png"))
    while is_loading(toks) and time.time() < loading_deadline:
        log(f"   loading... {toks[:3]}")
        time.sleep(2.5)
        screencap("outputs/logs/current.png")
        toks = clean_tokens(ocr_all("outputs/logs/current.png"))
    return toks


def _parse_step(raw):
    if isinstance(raw, dict):
        name = raw.get("name") or raw.get("label") or "?"
    else:
        name = str(raw)

    # 1. Check active game's visual element descriptions
    if hasattr(ACTIVE_GAME, "element_descriptions"):
        elems = ACTIVE_GAME.element_descriptions()
        for k, v in elems.items():
            if k.lower() == name.lower() or name.lower() in k.lower():
                return {"name": name, "ocr_label": name, "desc": v}

    # Bloons TD 6 specific fallback
    if name.upper() == "PLAY" and getattr(ACTIVE_GAME, "game_id", "") == "bloons_td_6":
        return {"name": name, "ocr_label": None,
                "desc": "the large round green PLAY button with a white play triangle "
                        "in the lower-center of the home screen (NOT 'PLAY SOCIAL')"}

    return {"name": name, "ocr_label": name, "desc": f"the '{name}' button or menu item"}


def _locate(step: dict, attempt: int, avoid=None):
    """Cascade: OCR first (cheap/exact), then VLM. Escalates by attempt."""
    if step.get("ocr_label") and attempt == 1:
        hit = find_text("outputs/logs/current.png", step["ocr_label"])
        if hit:
            return hit, "ocr"
    hit = vlm_locate("outputs/logs/current.png", step["desc"], avoid=avoid)
    if hit:
        return hit, "vlm"
    if step.get("ocr_label"):
        hit = find_text("outputs/logs/current.png", step["ocr_label"])
        if hit:
            return hit, "ocr-fallback"
    return None, None


# -- navigation ------------------------------------------------------
def navigate(nav_path: list) -> bool:
    log(f"NAVIGATE: {nav_path}")
    for i, raw in enumerate(nav_path):
        step = _parse_step(raw)
        name = step["name"]
        log(f" -> step '{name}'")
        ok = False
        for attempt in range(1, 4):
            _settle()
            if clear_popups(f"continue toward '{name}'"):
                _settle()
            save_shot(f"nav_{name}_a{attempt}")
            before = screen_signature()
            pt, method = _locate(step, attempt)
            if not pt:
                log(f"    not located (attempt {attempt})")
                time.sleep(2)
                continue
            tap(*pt, f"{name}[{method}]")
            if wait_for_change(before, timeout=10):
                log(f"    '{name}' OK (screen changed)")
                ok = True
                break
            log(f"    '{name}' no visible change yet; re-tapping same spot and waiting longer")
            tap(*pt, f"{name}[{method}-retap]")
            if wait_for_change(before, timeout=10):
                log(f"    '{name}' OK (on retap)")
                ok = True
                break
            log(f"    '{name}' tapped but screen unchanged — escalating/retrying")

        if not ok and i + 1 < len(nav_path):
            # The game may have skipped straight past this step on its own
            # (e.g. a "Continue Saved Game?" prompt jumps from PLAY straight
            # to difficulty-select, with no separate map-picker button at
            # all). If the NEXT step is already visible here, treat this one
            # as implicitly satisfied instead of failing the whole run.
            # Require TWO consistent locate calls, not one: a single noisy
            # false positive here would skip a real tap and strand the walk
            # on a screen that never actually advanced.
            nxt = _parse_step(nav_path[i + 1])
            pt1, _m = _locate(nxt, 1)
            pt2, _m = _locate(nxt, 1) if pt1 else (None, None)
            if pt1 and pt2:
                log(f"    '{name}' has no separate button here; "
                    f"already past it (next step '{nxt['name']}' is visible) — skipping")
                ok = True
        elif not ok and solidly_in_match():
            # This was the LAST step in the path -- if we're already in a
            # real match (the actual destination the whole path was aiming
            # for), the game must have skipped this step's screen on its own.
            log(f"    '{name}' has no separate button here; "
                f"already reached gameplay without it — skipping")
            ok = True

        if not ok:
            log(f"    FAILED to pass '{name}'")
            return False
    return True


# -- gameplay --------------------------------------------------------
def _defeat_showing(png_path: str = "outputs/logs/current.png") -> bool:
    """Cheap OCR check for a defeat / game-over screen (shared by the placement
    guard and the round-monitor loop)."""
    blob = " ".join(clean_tokens(ocr_all(png_path))).lower()
    return "defeat" in blob or "game over" in blob


def place_one(i: int, placed_pts: list, tower_desc: str = DART_DESC, tower_name: str = "Dart Monkey"):
    screencap("outputs/logs/current.png")
    save_shot(f"place{i}_before")
    cash0 = read_hud()["cash"]
    log(f" place {tower_name} #{i} (cash={cash0})")

    avoid = list(placed_pts)
    dart = vlm_locate_precise("outputs/logs/current.png", tower_desc)
    if not dart:
        log(f"    {tower_name} icon not found by VLM")
        return None

    # NOTE: we intentionally do NOT gate on an OCR-text-diff "did selection
    # register" check here. Selecting a tower in this game mostly just shows a
    # translucent range-circle overlay with little/no new OCR-readable text, so
    # a single-shot screen_changed() check almost always reads as "unchanged"
    # even when the tap worked. The cash-delta check below is a much more
    # reliable ground truth: it's the one thing that can't be faked by an
    # animation, and it covers both "selection worked" and "placement worked"
    # in a single signal.
    # A drop point whose surrounding box is this red almost certainly sits on
    # the balloon PATH / an invalid tile — Bloons paints the tower's range
    # circle red there. Used to tell "bad spot" apart from "gesture didn't take".
    RED_INVALID = 0.12

    def _placed(before):
        """Ground truth: a placement is real iff cash actually dropped."""
        screencap("outputs/logs/current.png")
        after = read_hud()["cash"]
        return (before is not None and after is not None and after < before), after

    for t in range(1, 4):
        grass = vlm_locate("outputs/logs/current.png", GRASS_DESC, avoid=avoid)
        if not grass:
            grass = vlm_locate("outputs/logs/current.png", GRASS_FALLBACK, avoid=avoid)
        if not grass:
            log("    no placeable grass found; re-locating tower")
            dart2 = vlm_locate_precise("outputs/logs/current.png", tower_desc)
            if dart2:
                dart = dart2
            continue

        # Primary mechanic: a genuine press-and-HOLD, carry, and release. A plain
        # quick swipe (or two disconnected taps) frequently does NOT register as a
        # placement in this UI — the tower never drops and cash is unchanged. The
        # hold is what makes the game grab the tower before we carry it to grass.
        drag(dart[0], dart[1], grass[0], grass[1],
             label=f"press-hold drag {tower_name} #{i} -> {grass}")
        save_shot(f"place{i}_try{t}_drag")
        ok, cash1 = _placed(cash0)
        if ok:
            log(f"    placed OK via press-hold drag (cash {cash0}->{cash1})")
            return grass

        # Diagnose WHY it didn't take, so the retry is targeted rather than blind:
        #   - high redness at the drop point  -> the spot itself is invalid (path);
        #     abandon it and ask the VLM for a different, more open grass point.
        #   - low redness                     -> the spot is fine but the gesture
        #     didn't register; try the explicit tap-select -> tap-place sequence.
        red = qac.redness("outputs/logs/current.png", grass[0], grass[1])
        if red >= RED_INVALID:
            log(f"    drop point looks invalid (red-fraction={red:.2f}, likely on path); "
                f"trying a different grass spot")
            avoid.append(grass)
            dart2 = vlm_locate_precise("outputs/logs/current.png", tower_desc)
            if dart2:
                dart = dart2
            continue

        log(f"    spot looks valid (red-fraction={red:.2f}) but drag didn't register; "
            f"trying explicit tap-select -> tap-place")
        tap(*dart, f"select {tower_name} (try {t})")
        time.sleep(0.6)
        tap(*grass, f"place#{i} try{t} {grass}")
        save_shot(f"place{i}_try{t}_taptap")
        ok, cash1 = _placed(cash0)
        if ok:
            log(f"    placed OK via tap+tap (cash {cash0}->{cash1})")
            return grass

        # If we've dropped out of a live match mid-placement (defeat, or the
        # game left the battlefield), stop retrying immediately -- the tower can
        # never place now, and further grass/drag attempts just burn time.
        if not solidly_in_match() or _defeat_showing("outputs/logs/current.png"):
            log("    no longer in a live match (defeat / left battlefield) -> aborting placement")
            return None

        log(f"    placement still didn't take (cash {cash0}->{cash1}); "
            f"re-selecting + trying a different grass spot")
        avoid.append(grass)
        dart2 = vlm_locate_precise("outputs/logs/current.png", tower_desc)
        if dart2:
            dart = dart2

    log("    could not place a tower after retries; skipping")
    return None


def start_and_fast_forward():
    """Start the first round and engage fast-forward ONCE.

    Returns (round, ff_engaged). Fast-forward is a TOGGLE (1x <-> 3x) and the
    game keeps the chosen speed across rounds, so it must be tapped exactly once
    -- re-tapping a round later would flip 3x back OFF. `ff_engaged` tells the
    caller whether that single tap already happened so it isn't repeated."""
    screencap("outputs/logs/current.png")
    save_shot("start_before")
    r0 = read_hud()["round"]
    st = vlm_locate_precise("outputs/logs/current.png", GREEN_DESC)
    if st:
        tap(*st, "START round")
        time.sleep(1.5)
    # The green double-chevron FAST-FORWARD button only appears once the round is
    # RUNNING; the frame captured above (between rounds) doesn't have it yet, so
    # locating FF on that stale frame made the VLM grab the nearby lightning-bolt
    # button by mistake. Re-capture now that the round has started.
    screencap("outputs/logs/current.png")
    ff_on = False
    ff = vlm_locate_precise("outputs/logs/current.png", FF_DESC)
    if ff:
        tap(*ff, "FAST-FORWARD 3x")
        ff_on = True
        time.sleep(0.5)
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(4)
        screencap("outputs/logs/current.png")
        if clear_popups("wait for the round to actually start"):
            screencap("outputs/logs/current.png")
        r1 = read_hud()["round"]
        if r0 is not None and r1 is not None and r1 > r0:
            log(f"    round advanced {r0}->{r1} (round started, {'3x' if ff_on else '1x'})")
            return r1, ff_on
    log("    round did not advance within 40 s")
    return (r0 or 0), ff_on


def _deploy_if_affordable(placed: list, cash=None) -> bool:
    """Economy loop: whenever accumulated round income has pushed cash above
    (DART_COST + CASH_RESERVE) and we're still under MAX_MONKEYS, drop another
    tower on fresh grass. For variety it ROTATES through TOWER_ROSTER (Dart ->
    Tack -> Bomb -> Ice -> ...); if the rotated tower is too pricey for the
    current cash (keeping the reserve) or its icon isn't found, it falls back to
    the cheapest Dart Monkey so a deploy still happens. `place_one` re-verifies
    every buy via the cash drop, so a failed/misread placement never corrupts
    `placed`. `cash` may be passed in to reuse a HUD read the caller already did.
    Returns True iff a tower was actually placed.
    """
    if len(placed) >= _MAX_UNITS:
        return False
    if cash is None:
        screencap("outputs/logs/current.png")
        cash = read_hud().get("cash")
    # Gate on affording at least the cheapest tower + reserve.
    if cash is None or cash < _CHEAPEST_UNIT + _CASH_RESERVE:
        return False

    # Pick the next tower in the rotation for variety; if we can't afford it
    # (keeping the reserve), fall back to the cheapest (Dart, index 0).
    name, desc, cost = TOWER_ROSTER[len(placed) % len(TOWER_ROSTER)]
    if cash < cost + _CASH_RESERVE:
        name, desc, cost = TOWER_ROSTER[0]
    log(f" economy: cash={cash} -> deploying {name} #{len(placed) + 1} "
        f"(reserve {_CASH_RESERVE})")
    spot = place_one(len(placed) + 1, placed, tower_desc=desc, tower_name=name)
    if spot:
        placed.append(spot)
        return True
    # Chosen tower couldn't be placed (misjudged cost / icon not found) -> try
    # the guaranteed-cheapest Dart Monkey once before giving up this cycle.
    if desc is not DART_DESC:
        log(f"    {name} didn't deploy; falling back to a Dart Monkey")
        spot = place_one(len(placed) + 1, placed, tower_desc=DART_DESC, tower_name="Dart Monkey")
        if spot:
            placed.append(spot)
            return True
    return False


def play(target_round: int = 5):
    from src.core.active_game import GAME
    if hasattr(GAME, "play"):
        try:
            return GAME.play(target_round=target_round)
        except Exception as e:
            log(f"   GAME.play error: {e}")

    log(f"GAMEPLAY: place monkeys, start, 3×, aim for round {target_round}")
    _settle()
    if clear_popups("settle into the battlefield before placing towers"):
        _settle()
    if not solidly_in_match():
        # navigate() can correctly report success after the last nav step
        # while still landing short of a real match -- e.g. tapping EASY
        # sometimes drops straight into the battlefield, and sometimes lands
        # on an intermediate difficulty rules card with its own PLAY button
        # first. navigate() has no way to know there's another screen still
        # in between; this is the one chance to push through it before
        # concluding the run genuinely stopped short.
        confirm = vlm_locate("outputs/logs/current.png", CONFIRM_PLAY_DESC)
        if confirm:
            log("    found a confirm/PLAY button on the current screen; "
                "tapping it before giving up on reaching a real match")
            tap(*confirm, "confirm into match")
            time.sleep(2.0)
            _settle()
            if clear_popups("settle into the battlefield before placing towers"):
                _settle()
        if not solidly_in_match():
            log(" NOT actually on a battlefield (no live round+cash HUD detected) -- "
                "navigation likely stopped short of a real match. Skipping placement "
                "rather than searching for a tower icon that can't be there.")
            return 0, 0, []
    placed = []
    for i in range(1, 4):
        spot = place_one(i, placed)
        if spot:
            placed.append(spot)
    log(f" monkeys placed: {len(placed)}")

    # Deeper in-match interaction checks (targeting, upgrades, selling,
    # shop scrolling, placement validity, hero ability) -- folded into this
    # same gameplay test rather than a separate scenario, run now while
    # towers are freshly placed and before round-progression burns the time
    # budget. scenarios.py reports through qa_common.record(), which is a
    # separate results channel from this function's own return value, so we
    # snapshot qac._RESULTS before the call and pull out only what it
    # appended -- that's what lets these checks surface in THIS scenario's
    # results.json entry instead of only existing in the console log.
    suite_results = []
    if placed:
        before_len = len(qac._RESULTS)
        try:
            scenarios.run_in_match_suite(qac, placed, DART_DESC)
        except Exception as e:
            log(f"  in-match suite raised: {e}")
        suite_results = qac._RESULTS[before_len:]

    last, ff_on = start_and_fast_forward()
    # Budget for pushing through to the target round. Each round-transition
    # search can itself burn 15-30s on VLM retries when the button isn't up
    # yet, so this scales with how many rounds are actually being asked for
    # -- a flat constant tuned for round 5 would starve a round-10 or
    # round-40 target of any real chance to get there.
    rounds_to_go = max(1, target_round - (last or 1))
    deadline = time.time() + max(360, rounds_to_go * 150)
    while time.time() < deadline and (last or 0) < target_round:
        time.sleep(8)
        screencap("outputs/logs/current.png")
        save_shot("monitor")
        if clear_popups("push past a round-transition interstitial (level up, reward, etc.)"):
            screencap("outputs/logs/current.png")
        if _defeat_showing("outputs/logs/current.png"):
            log(" DEFEAT detected")
            # T9 -- the one scenarios.py check that can't run alongside the
            # other six, since it needs a defeat screen already showing.
            # This is the only point in play() where that's actually true.
            before_len = len(qac._RESULTS)
            try:
                scenarios.defeat_restart(qac)
            except Exception as e:
                log(f"  defeat_restart raised: {e}")
            suite_results.extend(qac._RESULTS[before_len:])
            break
        hud = read_hud()
        r = hud.get("round")
        if r and r > (last or 0):
            last = r
            log(f"    round={last}")
        # Fast-forward is a TOGGLE and the game keeps the speed across rounds, so
        # we engage it exactly ONCE. If the opening tap missed (ff_on is False),
        # retry here until it takes; once ff_on is True we must NOT tap again, or
        # we'd flip 3x back OFF. (Re-tapping every round was the old bug.)
        if not ff_on:
            ff = vlm_locate_precise("outputs/logs/current.png", FF_DESC)
            if ff:
                tap(*ff, "engage FAST-FORWARD 3x")
                ff_on = True
                time.sleep(0.5)
        st = vlm_locate_precise("outputs/logs/current.png", GREEN_DESC)
        if st:
            tap(*st, "START next round")
            time.sleep(1.0)
        # Economy loop: reinvest round income into more towers as soon as we can
        # afford one (bounded by MAX_MONKEYS). This is what makes cash actually
        # translate into a stronger defense over the course of the match instead
        # of sitting unspent after the opening 3 placements.
        _deploy_if_affordable(placed, cash=hud.get("cash"))
    log(f" gameplay finished at round {last} ({len(placed)} monkeys deployed)")
    return len(placed), (last or 0), suite_results


# -- test harness ----------------------------------------------------
# -- stage-3 entrypoint: delegate to the custom orchestrator ----------
def execute_all():
    """STAGE 3 entrypoint. The real orchestration (parallel gameplay ∥
    compliance ∥ performance -> Validator -> Recovery self-heal) lives in
    orchestrator.py. Lazy import avoids a circular import (orchestrator imports
    navigate/play from this module)."""
    from src.core.orchestrator import run_cycle_and_report
    run_cycle_and_report(write_report=False)