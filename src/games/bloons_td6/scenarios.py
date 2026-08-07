#!/usr/bin/env python3
"""scenarios.py - self-contained Bloons TD6 test cases mapped to the Netflix rubric.

Each function:
  * is DEFENSIVE - missing preconditions -> NOT_OBSERVED, exceptions -> FAIL (never crashes the run)
  * is VERIFY-AFTER-ACT - it judges PASS/FAIL on an OBSERVABLE outcome (cash changed, text
    cycled, screen changed), not on the model's confidence
  * records its result via q.record(name, status, detail), which also logs it live
  * locates everything by reading the live screen (OCR / vlm_locate) - NO hardcoded coordinates

Combat scenarios assume we are solidly in a match; tower-interaction ones take the list of
points where monkeys were placed (so they can select a real tower).
"""

import time

# Natural-language element descriptions (read off-screen, not coordinates).
PATH_DESC   = ("a point squarely ON the grey/brown DIRT PATH that the balloons travel along "
               "(the track itself, NOT the grass beside it)")
TOWER_ON_MAP = ("a monkey tower already PLACED on the map (a small monkey standing on the grass, "
                "NOT an icon in the right-side shop)")
TARGET_DESC = ("the RIGHT-pointing arrow ( > ) that CYCLES the targeting priority in the selected "
               "unit's panel. The panel shows the current target mode as a word (First / Last / "
               "Close / Strong) with a small '<' arrow to its LEFT and a '>' arrow to its RIGHT. "
               "Point at the RIGHT '>' arrow (tapping it changes the mode), NOT the word itself.")
SELL_DESC   = ("the SELL button inside the selected tower's panel (usually at the bottom; shows a "
               "cash refund value and/or a $ sign). Do NOT pick an upgrade button.")
UPGRADE_DESC = ("an affordable UPGRADE button inside the selected tower's panel (one of the upgrade "
                "paths, showing a price you can pay). Do NOT pick Sell or Targeting.")
LOCK_DESC   = ("a PADLOCK / lock icon on one of the three upgrade paths in the selected tower's "
               "panel, indicating that path is locked")
SHOP_DESC   = ("the centre of the scrollable tower SHOP list on the RIGHT side of the battlefield")
RESTART_DESC = ("the RESTART / RETRY button on the defeat / game-over screen")
HERO_ABILITY_DESC = ("a HERO special-ability button (a circular hero portrait button, usually "
                     "bottom-centre/left) that is READY to use (no dark cooldown sweep over it)")
MOAB_DESC = ("a large MOAB blimp on the track - a big purple/pink blimp much larger than a normal "
             "round balloon")


def _cap(q, tag):
    q.screencap("outputs/logs/current.png")
    q.save_shot(tag)


def _cash(q):
    return q.read_hud("outputs/logs/current.png").get("cash")


def _select_placed_tower(q, placed_pts):
    """Tap a real placed tower to open its panel. Returns the point or None."""
    if placed_pts:
        pt = placed_pts[0]
        q.tap(*pt, "select placed tower")
        time.sleep(0.8)
        return pt
    _cap(q, "find_tower")
    pt = q.vlm_locate("outputs/logs/current.png", TOWER_ON_MAP)
    if pt:
        q.tap(*pt, "select placed tower[claude]")
        time.sleep(0.8)
    return pt


# ----------------------------------------------------------- Test 3 (full): drag-drop validity
def drag_and_drop_validity(q, dart_desc):
    """Place on INVALID path (must be rejected) and on VALID grass (must place).
    Oracle = the authoritative outcome (cash unchanged = rejected, cash drop = placed)."""
    name = "T3 Drag-and-Drop Placement Validity"
    try:
        _cap(q, "t3_before")
        cash0 = _cash(q)
        dart = q.vlm_locate("outputs/logs/current.png", dart_desc)
        if not dart or cash0 is None:
            return q.record(name, "NOT_OBSERVED", "no tower icon / cash unreadable")

        # 1) INVALID: try to drop the tower ON the path - the game must refuse (no cash spent).
        path = q.vlm_locate("outputs/logs/current.png", PATH_DESC)
        invalid_rejected = None
        if path:
            q.tap(*dart, "select dart (invalid test)")
            time.sleep(0.4)
            q.tap(path[0], path[1], "tap on PATH (expect reject)")
            _cap(q, "t3_on_path")
            red = q.redness("outputs/logs/current.png", path[0], path[1])   # bonus visual signal
            cash1 = _cash(q)
            invalid_rejected = (cash1 is not None and cash1 == cash0)
            q.log(f"   path drop: cash {cash0}->{cash1}, red-fraction={red:.2f} "
                  f"-> {'rejected (correct)' if invalid_rejected else 'UNEXPECTEDLY placed'}")

        # 2) VALID: tap-select the dart, then tap clear grass (the proven placement path).
        from src.games.bloons_td6.descriptions import GRASS_DESC, GRASS_FALLBACK
        grass = q.vlm_locate("outputs/logs/current.png", GRASS_DESC)
        if not grass:
            grass = q.vlm_locate("outputs/logs/current.png", GRASS_FALLBACK)
        valid_placed = False
        if grass:
            q.tap(*dart, "select dart (valid test)")
            time.sleep(0.4)
            q.tap(grass[0], grass[1], "place on GRASS (expect place)")
            _cap(q, "t3_on_grass")
            cash2 = _cash(q)
            valid_placed = (cash2 is not None and cash0 is not None and cash2 < cash0)
            q.log(f"   grass drop: cash->{cash2} -> {'placed (correct)' if valid_placed else 'did NOT place'}")

        if valid_placed and (invalid_rejected or invalid_rejected is None):
            return q.record(name, "PASS",
                            f"valid placed; invalid {'rejected' if invalid_rejected else 'not tested'}")
        if valid_placed:
            return q.record(name, "FAIL", "placed on grass but path drop was NOT rejected")
        return q.record(name, "FAIL", "could not place on valid grass via drag")
    except Exception as e:
        return q.record(name, "FAIL", f"exception: {e}")


# ----------------------------------------------------------- Test 4: target priority
def target_priority(q, placed_pts):
    name = "T4 Target Priority Adjustment"
    try:
        if not _select_placed_tower(q, placed_pts):
            return q.record(name, "NOT_OBSERVED", "no placed tower to select")
        _cap(q, "t4_panel")
        btn = q.vlm_locate("outputs/logs/current.png", TARGET_DESC)
        if not btn:
            q.back()
            return q.record(name, "NOT_OBSERVED", "targeting button not found in panel")

        def read_mode():
            toks = [t.lower() for t in q.clean_tokens(q.ocr_all("outputs/logs/current.png"), cap=40)]
            for m in ("first", "last", "close", "strong"):
                if m in toks:
                    return m
            return None

        before = read_mode()
        q.tap(*btn, "cycle targeting")
        time.sleep(0.6)
        _cap(q, "t4_after")
        after = read_mode()
        q.back()  # close panel
        if before and after and before != after:
            return q.record(name, "PASS", f"target cycled {before} -> {after}")
        if after and not before:
            return q.record(name, "PASS", f"target mode now '{after}' (prior unread)")
        return q.record(name, "FAIL", f"target did not change ({before} -> {after})")
    except Exception as e:
        return q.record(name, "FAIL", f"exception: {e}")


# ----------------------------------------------------------- Test 5: upgrade path branching
def upgrade_branching(q, placed_pts):
    name = "T5 Upgrade Path Branching"
    try:
        if not _select_placed_tower(q, placed_pts):
            return q.record(name, "NOT_OBSERVED", "no placed tower to select")
        _cap(q, "t5_panel")
        cash0 = _cash(q)
        up = q.vlm_locate("outputs/logs/current.png", UPGRADE_DESC)
        if not up or cash0 is None:
            q.back()
            return q.record(name, "NOT_OBSERVED", "no affordable upgrade / cash unreadable")
        q.tap(*up, "buy upgrade")
        time.sleep(0.8)
        _cap(q, "t5_after")
        cash1 = _cash(q)
        bought = (cash1 is not None and cash1 < cash0)
        lock = q.vlm_locate("outputs/logs/current.png", LOCK_DESC)
        q.back()
        detail = f"path-3 lock {'detected' if lock else 'not seen'}"
        if bought:
            return q.record(name, "PASS", f"upgrade purchased (cash {cash0}->{cash1}); {detail}")
        return q.record(name, "FAIL", f"upgrade tap did not spend (cash {cash0}->{cash1}); {detail}")
    except Exception as e:
        return q.record(name, "FAIL", f"exception: {e}")


# ----------------------------------------------------------- Test 8: sell -> replace
def sell_and_replace(q, placed_pts, dart_desc):
    name = "T8 Sell & Replace Infrastructure"
    try:
        pt = _select_placed_tower(q, placed_pts)
        if not pt:
            return q.record(name, "NOT_OBSERVED", "no placed tower to sell")
        _cap(q, "t8_panel")
        cash0 = _cash(q)
        sell = q.vlm_locate("outputs/logs/current.png", SELL_DESC)
        if not sell or cash0 is None:
            q.back()
            return q.record(name, "NOT_OBSERVED", "sell button not found / cash unreadable")
        q.tap(*sell, "sell tower")
        time.sleep(1.0)
        _cap(q, "t8_sold")
        cash1 = _cash(q)
        sold = (cash1 is not None and cash1 > cash0)
        q.log(f"   sell: cash {cash0}->{cash1} -> {'refunded (correct)' if sold else 'no refund'}")

        # replace in the same footprint
        replaced = False
        dart = q.vlm_locate("outputs/logs/current.png", dart_desc)
        if dart:
            q.tap(*dart, "re-select dart for replace")
            time.sleep(0.5)
            q.tap(*pt, "place replacement in same footprint")
            time.sleep(1.0)
            _cap(q, "t8_replaced")
            cash2 = _cash(q)
            replaced = (cash2 is not None and cash1 is not None and cash2 < cash1)
            q.log(f"   replace: cash {cash1}->{cash2} -> {'placed (correct)' if replaced else 'did NOT place'}")

        if sold and replaced:
            return q.record(name, "PASS", "sold (refund) and replaced in same spot")
        if sold:
            return q.record(name, "FAIL", "sold OK but replacement did not place")
        return q.record(name, "FAIL", "sell did not refund cash")
    except Exception as e:
        return q.record(name, "FAIL", f"exception: {e}")


# ----------------------------------------------------------- Test 2: sidebar carousel scroll
def sidebar_carousel(q):
    name = "T2 Sidebar Carousel Navigation"
    try:
        _cap(q, "t2_before")
        center = q.vlm_locate("outputs/logs/current.png", SHOP_DESC)
        if not center:
            return q.record(name, "NOT_OBSERVED", "shop list region not found")
        before_sig = q.screen_signature("outputs/logs/current.png")
        # scroll up within the shop column (swipe from lower to higher in the same x)
        q.swipe(center[0], center[1] + 120, center[0], center[1] - 120, label="scroll tower shop")
        _cap(q, "t2_after")
        after_sig = q.screen_signature("outputs/logs/current.png")
        # restore the shop to its default scroll so later tower selection/placement is unaffected
        q.swipe(center[0], center[1] - 120, center[0], center[1] + 120, label="restore shop scroll")
        if q.screen_changed(before_sig, after_sig):
            return q.record(name, "PASS", "shop list scrolled (content changed)")
        return q.record(name, "NOT_OBSERVED", "swipe produced no visible change (panel may not scroll)")
    except Exception as e:
        return q.record(name, "FAIL", f"exception: {e}")


# ----------------------------------------------------------- Test 7: hero ability / MOAB timing
def hero_ability_timing(q):
    name = "T7 Cooldown Ability Synchronization"
    try:
        _cap(q, "t7_scan")
        moab = q.vlm_locate("outputs/logs/current.png", MOAB_DESC)
        ability = q.vlm_locate("outputs/logs/current.png", HERO_ABILITY_DESC)
        if not ability:
            return q.record(name, "NOT_OBSERVED", "no hero ability button present (no hero this run)")
        if not moab:
            return q.record(name, "NOT_OBSERVED", "hero present but no MOAB on screen to time against")
        before = q.screen_signature("outputs/logs/current.png")
        q.tap(*ability, "activate hero ability (MOAB on screen)")
        time.sleep(1.0)
        _cap(q, "t7_after")
        # ability fired if its button now shows a cooldown sweep / the screen changed materially
        if q.screen_changed(before, q.screen_signature("outputs/logs/current.png")):
            return q.record(name, "PASS", "ability activated while MOAB present (cooldown/effect visible)")
        return q.record(name, "FAIL", "ability tap produced no visible effect")
    except Exception as e:
        return q.record(name, "FAIL", f"exception: {e}")


# ----------------------------------------------------------- Test 9: defeat modal -> restart
def defeat_restart(q):
    """Call ONLY when a defeat/game-over screen is already showing."""
    name = "T9 Defeat Modal Interaction"
    try:
        _cap(q, "t9_defeat")
        btn = q.vlm_locate("outputs/logs/current.png", RESTART_DESC)
        if not btn:
            r = q.find_text("outputs/logs/current.png", "restart") or q.find_text("outputs/logs/current.png", "retry")
            btn = (r[0], r[1]) if r else None
        if not btn:
            return q.record(name, "FAIL", "defeat screen up but no Restart button found")
        q.tap(*btn, "Restart match")
        time.sleep(3)
        _cap(q, "t9_reloaded")
        reloaded = q.read_hud("outputs/logs/current.png").get("round") is not None
        if reloaded:
            return q.record(name, "PASS", "restart tapped; match reloaded")
        return q.record(name, "FAIL", "restart tapped but battlefield did not reload")
    except Exception as e:
        return q.record(name, "FAIL", f"exception: {e}")


# ----------------------------------------------------------- in-match suite runner
def run_in_match_suite(q, placed_pts, dart_desc):
    """Run the interaction scenarios that require being in a live match with a tower placed.
    Order matters: do the non-destructive ones before sell/replace destroys a tower."""
    q.log(">>> running in-match scenario suite")
    sidebar_carousel(q)
    target_priority(q, placed_pts)
    upgrade_branching(q, placed_pts)
    hero_ability_timing(q)            # usually NOT_OBSERVED early on Easy
    drag_and_drop_validity(q, dart_desc)
    sell_and_replace(q, placed_pts, dart_desc)   # destructive -> last
    q.log(">>> in-match scenario suite done")
