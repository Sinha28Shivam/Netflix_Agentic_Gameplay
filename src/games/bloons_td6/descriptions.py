"""
agents/gameplay_descriptions.py
Natural-language element descriptions shared between run_one_game.py and scenarios.py.
All descriptions are fed to the VLM (vlm_locate) — NO hardcoded coordinates.
"""

# ----- Tower shop -----
DART_DESC = (
    "the cheapest UNLOCKED Primary tower icon in the tower shop on the RIGHT. The shop is "
    "a TWO-COLUMN grid of rounded square icons; this is the brown Dart Monkey icon showing "
    "a PRICE around $170. It MUST show a price and MUST NOT have a PADLOCK; IGNORE any "
    "greyed-out or padlocked icon. Return a point squarely ON the MONKEY ARTWORK, INSIDE "
    "the coloured icon tile (about its centre) — NOT the price text below it, and NOT the "
    "empty tan/wood panel margin to the RIGHT of the icons. The point must land on the "
    "tappable picture itself, not the border beside it."
)

# ----- Other Primary towers (for a varied deployment; must be UNLOCKED, no padlock) -----
BOMB_DESC = (
    "the Bomb Shooter tower icon in the shop grid on the RIGHT: a dark CANNON / mortar "
    "that fires bombs, showing a PRICE and with no PADLOCK. Return a point squarely ON "
    "the cannon artwork, INSIDE the coloured icon tile (about its centre) -- not the "
    "price text and not the panel margin beside it."
)

ICE_DESC = (
    "the Ice Monkey tower icon in the shop grid on the RIGHT: a blue/white monkey with a "
    "frost / snowflake theme, showing a PRICE and with no PADLOCK. Return a point squarely "
    "ON the monkey artwork, INSIDE the coloured icon tile (about its centre) -- not the "
    "price text and not the panel margin beside it."
)

TACK_DESC = (
    "the Tack Shooter tower icon in the shop grid on the RIGHT: a round wooden tower that "
    "fires tacks/spikes outward in all directions, showing a PRICE and with no PADLOCK. "
    "Return a point squarely ON the tower artwork, INSIDE the coloured icon tile (about "
    "its centre) -- not the price text and not the panel margin beside it."
)

# ----- Map grass -----
GRASS_DESC = (
    "a point to drop a tower, on clear GREEN GRASS. Prefer a LARGE OPEN patch of green "
    "meadow in the CENTRE of the map, well clear of everything else. Keep at least a "
    "tower's width of CLEARANCE (roughly 120 px) from: the grey/brown DIRT PATH the "
    "balloons travel on, any water/river/pond, the tower shop panel on the right edge, "
    "the top HUD bar, and any monkey already placed. Do NOT return a point on or hugging "
    "the path — a tower dropped there is rejected. Return the CENTRE of the most open "
    "grass area you can see; do not refuse if any reasonable spot exists."
)

GRASS_FALLBACK = (
    "ANY clearly placeable patch of green grass that is NOT on the dirt path, NOT on "
    "water, NOT under the right-hand shop panel or top HUD, and NOT on top of an "
    "existing monkey. Ignore how open it is — just pick the single most obviously-grass "
    "pixel away from the path and return its centre."
)

# ----- Round control buttons -----
GREEN_DESC = (
    "the START / NEXT-ROUND button in the BOTTOM-RIGHT corner. There are two round buttons "
    "side by side there. The START button is the RIGHTMOST one and shows a SINGLE white "
    "right-pointing PLAY TRIANGLE (one solid play arrow). The other button to its LEFT is "
    "fast-forward and shows a DOUBLE arrow / double-chevron — do NOT pick that one. IGNORE "
    "COLOUR (the buttons may be green, blue, yellow or orange in different runs) — identify "
    "START purely by the SINGLE play triangle and its rightmost position. It appears only "
    "between rounds; if a round is running and no single-play-triangle button is visible, "
    "treat it as NOT FOUND. Return the CENTER of that play-triangle button."
)

FF_DESC = (
    "the FAST-FORWARD button in the BOTTOM-RIGHT: a GREEN square button showing a white "
    "DOUBLE right-pointing CHEVRON -- TWO play arrows side by side ( >> ). It toggles 3x "
    "speed and appears once a round is running. Identify it STRICTLY by the DOUBLE (two) "
    "arrows on a GREEN button. "
    "Do NOT return the YELLOW/ORANGE LIGHTNING-BOLT / thunderbolt button -- that is a "
    "different control, NOT fast-forward. "
    "Do NOT return a green button that shows only a SINGLE play triangle -- that is the "
    "START button, not fast-forward. "
    "Return the CENTRE of the green double-chevron button."
)

# ----- Navigation -----
BACK_DESC = (
    "the BACK / RETURN button: a curved or left-pointing ARROW (a 'go back' / U-turn arrow), "
    "usually in the TOP-LEFT corner of the screen, that closes the current shop or menu and "
    "returns to the previous screen. Ignore colour. Return its center."
)

CONFIRM_PLAY_DESC = (
    "the green PLAY button (round, with a white play triangle) used to confirm and launch "
    "into the match. This may appear on a difficulty RULES/INFO card -- a screen showing "
    "descriptive text (e.g. 'On Easy, monkeys cost less...') and difficulty badges "
    "(Beginner/Intermediate/Advanced/Expert) -- if the game stopped there on its way into "
    "a match instead of going straight to the battlefield. If no such button is visible "
    "anywhere on screen, return not found rather than guessing."
)
 