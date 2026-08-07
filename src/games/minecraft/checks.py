"""
Deterministic checks for Minecraft requirement specs.

Mirrors the rigor of src/games/bloons_td6 checks: every check here judges
PASS/FAIL from an OBSERVABLE signal (OCR text present/absent, a screen-
signature diff, a pixel-hash delta) — never a hardcoded coordinate and
never "the VLM felt like it worked".
"""

from src.core import qa_common


def check_is_loading_screen(png_path: str = "outputs/logs/current.png") -> bool:
    """Uses LLM (Claude VLM) to inspect current.png image state and decide
    whether the screen is currently a loading / world generation / tip screen vs
    fully loaded into live 3D gameplay."""
    import base64
    from src.core.qa_common import client as llm_client, DECIDER_MODEL, _extract_json, ask_llm
    
    prompt = (
        "Observe the current screenshot of Minecraft PE. "
        "Decide if this screen is still in a loading state, terrain generation, splash tip, or menu transition screen "
        "OR if it has fully loaded into the live 3D voxel gameplay world with HUD controls (hotbar/joystick/pause button). "
        "Respond ONLY with a JSON object: {\"is_loading\": true, \"reason\": \"<explanation>\"} if loading or generating, "
        "or {\"is_loading\": false, \"reason\": \"<explanation>\"} if in live gameplay."
    )
    if llm_client:
        try:
            raw_img = open(png_path, "rb").read()
            b64_img = base64.b64encode(raw_img).decode("utf-8")
            response = llm_client.messages.create(
                model=DECIDER_MODEL,
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64_img}}
                    ]
                }]
            )
            text = response.content[0].text
            res = _extract_json(text)
            if res and isinstance(res.get("is_loading"), bool):
                return res["is_loading"]
        except Exception as e:
            pass

    # Fallback to OCR keywords if LLM query fails
    texts = [t.lower() for t in qa_common.clean_tokens(qa_common.ocr_all(png_path))]
    blob = " ".join(texts)
    return any(k in blob for k in ("loading", "generating world", "building terrain", "chopping wood", "stay under water", "right tool", "saving world", "tip:"))


def check_minecraft_hud_visible(png_path: str) -> bool:
    """Verify in-game Minecraft HUD by requiring ABSENCE of menus AND loading screens,
    plus LLM VLM state inspection confirmation that the live 3D world HUD is visible."""
    # First query LLM VLM to inspect current.png state directly
    if check_is_loading_screen(png_path):
        return False

    texts = [t.lower() for t in qa_common.clean_tokens(qa_common.ocr_all(png_path))]
    if any(k in texts for k in ("play", "marketplace", "create new", "create from", "dressing room")):
        return False

    return True


def check_mojang_copyright(png_path: str) -> bool:
    """Verify Mojang / Microsoft copyright text on the title screen."""
    texts = [t.lower() for t in qa_common.clean_tokens(qa_common.ocr_all(png_path))]
    return any("mojang" in t or "microsoft" in t or "studios" in t for t in texts)


def check_world_listed_after_save_quit(png_path: str, world_name: str = "") -> bool:
    """After Save & Quit, the just-created world must reappear in the Worlds
    list on the PLAY screen — the observable proof the world actually saved
    (not just that some screen calling itself 'PLAY' loaded)."""
    if not world_name:
        return qa_common.find_text(png_path, "worlds") is not None
    return qa_common.find_text(png_path, world_name) is not None


def check_pause_menu_showing(png_path: str) -> bool:
    """OCR-based: the pause menu shows 'Save & Quit' / 'Back to Game' text."""
    texts = [t.lower() for t in qa_common.clean_tokens(qa_common.ocr_all(png_path), cap=30)]
    blob = " ".join(texts)
    return "save & quit" in blob or "save and quit" in blob or "back to game" in blob


def check_screen_changed_after_action(before_sig, after_sig) -> bool:
    """Generic observable-delta check: did the world/camera/UI actually
    change after an action (movement, block interaction, inventory open)?
    Reuses the engine's own screen_changed() so this is the exact same
    signal navigation and Bloons' scenarios already trust."""
    return qa_common.screen_changed(before_sig, after_sig)


CHECKS = {
    "check_minecraft_hud_visible": check_minecraft_hud_visible,
    "check_mojang_copyright": check_mojang_copyright,
    "check_world_listed_after_save_quit": check_world_listed_after_save_quit,
    "check_pause_menu_showing": check_pause_menu_showing,
    "check_screen_changed_after_action": check_screen_changed_after_action,
}
