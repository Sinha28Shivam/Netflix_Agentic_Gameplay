import json
import re

from src.core.config import VISION_MODEL as QWEN_MODEL

# The scene enum is per-game. This default mirrors the original Bloons enum so
# anything importing VISION_SYSTEM_PROMPT keeps working; VisionAgent itself
# builds the prompt from the ACTIVE game's scene_vocabulary at construction.
_DEFAULT_SCENES = ("loading|main_menu|map_selection|difficulty_selection|game_mode|"
                   "placement|in_round|between_rounds|victory|defeat|dialog|unknown")


def build_system_prompt(scene_enum: str = _DEFAULT_SCENES) -> str:
    return f"""
You are the Vision Agent for an automated game-QA system.

You NEVER decide actions, plan, or suggest taps.
You ONLY describe the visible game state as JSON.

Schema:
{{
  "scene": "{scene_enum}",
  "blocking_modal": {{"present": false, "title": "", "buttons": []}},
  "resources": {{"cash": null, "lives": null, "round": null}},
  "actionable_elements": [
    {{"label": "", "kind": "button", "x": 0, "y": 0, "enabled": true}}
  ],
  "confidence": 0.0
}}

Only report visible facts. Never guess. Return JSON only, no commentary.
"""


VISION_SYSTEM_PROMPT = build_system_prompt()


class VisionAgent:
    def __init__(self, client, scene_vocabulary=None):
        self.client = client
        if scene_vocabulary is None:
            try:
                from src.core.active_game import GAME
                scene_vocabulary = GAME.scene_vocabulary
            except Exception:
                scene_vocabulary = None
        self.system_prompt = (build_system_prompt("|".join(scene_vocabulary))
                              if scene_vocabulary else VISION_SYSTEM_PROMPT)

    def observe(self, screenshot_b64, ui_texts):
        ui_summary = "\n".join(ui_texts[:20])

        response = self.client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"UI TEXT\n\n{ui_summary}\n\nAnalyze the screenshot. Return JSON only.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                        },
                    ],
                },
            ],
            max_tokens=700,
        )

        return self._parse(response.choices[0].message.content)

    @staticmethod
    def _parse(text):
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {"scene": "unknown", "confidence": 0.0}