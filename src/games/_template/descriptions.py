"""
Natural-language element descriptions for __DISPLAY_NAME__.

Each value is a prompt handed to the VLM (vlm_locate) to find that element on
screen — describe it the way you'd tell a person, and DO NOT use coordinates.
Keyed by a role your profile/scenarios reference.
"""

ELEMENTS = {
    "play_button": (
        "the main PLAY / START button that begins a game, usually a large "
        "brightly-coloured button near the centre or bottom of the main menu"
    ),
    # Add the elements your scenarios need to locate, e.g.:
    # "settings_button": "the gear / cog icon that opens settings",
}
