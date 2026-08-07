"""
Natural-language element descriptions for Subway Surfers menus.

Used by the VLM (vlm_locate) for MENU navigation only (boot -> start a run,
handle revive/game-over). In-run dodging does NOT use these — it uses the
real-time CV path (perception.py) instead.
"""

ELEMENTS = {
    "play_button": (
        "the large button that starts a run from the main menu — usually a big "
        "PLAY / tap-to-start prompt in the lower-center of the title screen"
    ),
    "tap_to_start": (
        "the 'TAP TO PLAY' / 'TAP TO START' prompt shown over the character on "
        "the main screen"
    ),
    "revive_decline": (
        "the button that DECLINES a revive / continue offer on the game-over "
        "screen — the 'NO THANKS' / X / skip button, NOT the golden 'SAVE ME' / "
        "revive-with-keys button"
    ),
    "pause_button": "the pause button (usually a small ❚❚ icon in a top corner during a run",
    "resume_button": "the resume / play button on the pause overlay",
    "shop_button": "the SHOP button on the main menu",
    "back_button": "the back / close arrow that returns to the previous screen",
}
