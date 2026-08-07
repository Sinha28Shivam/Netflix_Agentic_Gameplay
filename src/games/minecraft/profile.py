"""
Minecraft (com.mojang.minecraftpe) — Game Profile Integration.
"""

from src.games.base import GameProfile, PlayResult
from src.games.registry import register


@register
class Minecraft(GameProfile):
    # ---- Identity ----
    game_id = "minecraft"
    display_name = "Minecraft"
    package = "com.mojang.minecraftpe"
    activity = "com.mojang.minecraftpe.Minecraft"

    # ---- Mission ----
    mission_summary = "Navigate from main menu through Play -> Create World -> Control Mode into a live world, then exercise movement/block/hotbar/pause/save gameplay"
    goal = {"target_scene": "in_game"}

    # ---- Scene Vocabulary matching exact UI flow ----
    scene_vocabulary = [
        "loading", "main_menu", "play_menu", 
        "create_from_menu", "create_world_config", "control_mode", 
        "in_game", "pause_menu", "settings", "marketplace", "dialog", "victory", "defeat", "unknown"
    ]

    # ---- Requirements ----
    def build_requirements(self):
        from . import specs
        return specs.REQUIREMENTS

    # ---- Element Descriptions ----
    def element_descriptions(self):
        from . import descriptions
        return descriptions.ELEMENTS

    # ---- Check Registry ----
    def gameplay_check_registry(self):
        from . import checks
        return checks.CHECKS

    # ---- Scene Objectives ----
    def objective_for_scene(self, scene: str) -> str:
        return {
            "main_menu": "Tap the green 'Play' button to open the Play screen",
            "play_menu": "Tap the green 'Create new world' button under Worlds tab",
            "create_from_menu": "Tap the green 'Create new world' option on the left panel",
            "create_world_config": "Tap the green 'CREATE' button on the left panel to build world",
            "control_mode": "Tap the bright green 'SELECT' button to confirm control mode",
            "in_game": "Move with the joystick, look around, interact with a block, cycle the hotbar",
            "pause_menu": "Tap 'Save & Quit'",
        }.get(scene, "Observe screen")

    # ---- Scene Tagging & Match Detection ----
    # NOTE: on-device OCR frequently confuses similar-looking glyphs
    # (S<->5, O<->0, l<->1, g<->9) — e.g. "Settings" reads as "5ettings",
    # "Servers" as "5ervers". _normalize_ocr() undoes the common digit-for-
    # letter substitutions before any keyword matching below, and checks
    # are ordered from most distinctive/rare signal to most generic so a
    # noisy match on a common word (like "play") can't shadow a specific one.
    @staticmethod
    def _normalize_ocr(text: str) -> str:
        text = text.lower()
        return text.translate(str.maketrans({
            "0": "o", "1": "l", "5": "s", "8": "b", "9": "g",
        }))

    def tag_scene(self, tokens: list, png_path: str = "outputs/logs/current.png") -> str:
        blob = self._normalize_ocr(" ".join(tokens))

        # 1. Pause menu — "Game is paused" OCRs cleanly and is unique to this screen.
        if ("game is paused" in blob or "resume game" in blob
                or "back to game" in blob or ("save" in blob and "quit" in blob)):
            return "pause_menu"

        # 2. Loading screen — tip text OCRs noisily ("Loadling.."), but "load"
        #    survives, as do the flavor-text fragments.
        if "load" in blob or "chopping wood" in blob or "right tool for the job" in blob or "building terrain" in blob or "generating world" in blob:
            return "loading"

        # 3. Control mode dialog.
        if "control mode" in blob or "joystick" in blob or "d-pad" in blob:
            return "control_mode"

        # 4. World-creation config form — "Game mode" / "Difficulty" / the
        #    Creative-Survival toggle OCR cleanly and don't appear elsewhere.
        if "gamemode" in blob or "game mode" in blob or "difficulty" in blob or (
                "creative" in blob and "world" in blob):
            self._handle_create_world_config(png_path)
            return "create_world_config"

        # 5. "Create from..." marketplace intermediate screen.
        if "create from" in blob or "marketplace pass" in blob:
            return "create_from_menu"

        # 6. PLAY/worlds list screen.
        if "play" in blob and ("worlds(" in blob or "worlds (" in blob
                                or "realms" in blob or "servers" in blob):
            return "play_menu"

        # 7. Main title/menu screen.
        if "minecraft" in blob and ("marketplace" in blob or "settings" in blob
                                    or "dungeons" in blob or "mojang" in blob
                                    or "play" in blob):
            return "main_menu"

    created_world_name: str = "QA_World_Test"

    def _handle_create_world_config(self, png_path: str = "outputs/logs/current.png"):
        """Configures a unique world name and queries LLM to choose between Easy or Peaceful difficulty."""
        import time
        from datetime import datetime
        import src.core.qa_common as qac

        if getattr(self, "_config_done", False):
            return

        self.created_world_name = f"QA_World_{datetime.now().strftime('%H%M%S')}"
        qac.log(f"🎮 Configuring New Minecraft World: '{self.created_world_name}'")

        # Ask LLM to pick difficulty: Easy or Peaceful
        prompt = (
            "You are choosing a difficulty setting for a Minecraft QA testing session. "
            "Respond ONLY with a JSON object specifying 'difficulty' as either 'easy' or 'peaceful', and a brief 'reason'. "
            "Example: {\"difficulty\": \"peaceful\", \"reason\": \"Ensures mobs do not disrupt initial QA movement checks\"}"
        )
        difficulty_choice = "easy"
        try:
            raw_res = qac.ask_llm(prompt)
            parsed = qac._extract_json(raw_res)
            if parsed and parsed.get("difficulty") in ("easy", "peaceful"):
                difficulty_choice = parsed["difficulty"]
                qac.log(f"🤖 LLM selected difficulty: '{difficulty_choice.upper()}' ({parsed.get('reason', '')})")
        except Exception as e:
            qac.log(f"   LLM difficulty prompt failed: {e}; defaulting to 'easy'")

        # Try to locate and click world name input field, then type world name
        elems = self.element_descriptions()
        name_desc = elems.get("world_name_input", "the text input box for World Name at the top of the create world config menu")
        name_pt = qac.vlm_locate(png_path, name_desc)
        if not name_pt:
            name_pt = qac.find_text(png_path, "World name") or qac.find_text(png_path, "My World")
        if name_pt:
            qac.tap(*name_pt, f"tap World Name field")
            time.sleep(0.5)
            from src.device.device import text_input
            text_input(self.created_world_name, label=f"type world name {self.created_world_name}")
            time.sleep(0.5)
        else:
            qac.log(f"   world_name_input field not located on screen; world name setting skipped")

        # Try to locate and click chosen difficulty setting
        diff_key = f"difficulty_{difficulty_choice}"
        desc = elems.get(diff_key, f"the '{difficulty_choice}' difficulty option button under Difficulty settings")
        pt = qac.vlm_locate(png_path, desc)
        if pt:
            qac.tap(*pt, f"select difficulty {difficulty_choice}")
            time.sleep(0.5)

        self._config_done = True


    def is_in_match(self, png_path: str = "outputs/logs/current.png") -> bool:
        from .checks import check_minecraft_hud_visible, check_is_loading_screen
        if check_is_loading_screen(png_path):
            return False
        return check_minecraft_hud_visible(png_path)

    # ---- Goal Detection ----
    def is_goal_reached(self, state: dict) -> bool:
        return state.get("scene") == "in_game"

    # ---- In-world gameplay: movement / block interaction / hotbar / pause / save ----
    def run_in_match_suite(self, q, world_name: str = ""):
        """Runs the observable-delta-verified scenario suite (scenarios.py)
        against the live in-game world. Mirrors BloonsTD6.run_in_match_suite."""
        from . import scenarios
        return scenarios.run_in_match_suite(q, self.element_descriptions(), world_name)

    def wait_for_world_load(self, timeout: int = 120) -> bool:
        import time
        import src.core.qa_common as qac
        from .checks import check_is_loading_screen
        deadline = time.time() + timeout
        qac.log("⏳ Waiting for Minecraft world generation & loading screen to finish...")
        time.sleep(4.0)  # Let world generation/loading screen open cleanly
        while time.time() < deadline:
            qac.screencap("outputs/logs/current.png")
            is_loading = check_is_loading_screen("outputs/logs/current.png")
            if is_loading:
                qac.log("   world is still generating / loading (LLM state check: loading=True)...")
                time.sleep(3.0)
                continue
            qac.log("✅ Minecraft in-game world loaded cleanly (LLM state check: loading=False)!")
            return True
        return self.is_in_match("outputs/logs/current.png")

    def play(self, ctx=None, *args, **kwargs) -> PlayResult:
        """In-world action routine: confirm we're actually in a live world,
        then run the full movement/block/hotbar/pause/save scenario suite.
        Unlike Bloons' economy loop this game has no round/cash progression
        to drive — the play loop's job is to genuinely EXERCISE the world
        (move, look, mine/place, cycle hotbar, pause/resume, save & quit)
        and record every result via q.record(), exactly like Bloons does."""
        import src.core.qa_common as qac

        # Wait for world load to complete after CREATE/SELECT navigation
        loaded = self.wait_for_world_load(timeout=120)

        if not loaded:
            qac.log("Minecraft.play(): world load timed out or not in live world yet — skipping in-world suite")
            return PlayResult(placed=[], rounds=None, suite_ran=False,
                              notes={"reason": "not_in_game"})

        world_name = ""
        if isinstance(ctx, dict):
            world_name = ctx.get("world_name", "")

        before_len = len(qac._RESULTS)
        try:
            self.run_in_match_suite(qac, world_name=world_name)
        except Exception as e:
            qac.log(f"Minecraft.play(): in-world suite raised: {e}")
        suite_results = qac._RESULTS[before_len:]

        return PlayResult(
            placed=[],
            rounds=None,
            suite_ran=bool(suite_results),
            notes={"suite": suite_results},
        )
