import json
import re

from src.core.config import QWEN_MODEL

DECISION_SYSTEM_PROMPT = """
You are the Decision Agent for an automated game-QA system.

You NEVER receive screenshots. You ONLY receive structured game state.

Your job is to drive the game to satisfy the QA objective, not to maximize score.

Return ONE action only, as JSON, using one of these shapes:
{"action": "tap", "target": "Play", "why": "Move to map selection."}
{"action": "wait", "ms": 3000, "why": "Round is running."}
{"action": "swipe_left", "why": "Reveal next map."}
{"action": "swipe_right", "why": "Reveal next map."}
{"action": "swipe_up", "why": "Scroll list."}
{"action": "swipe_down", "why": "Scroll list."}
{"action": "done", "result": "objective_met", "why": "Reached Round 10."}

Never return coordinates. Never return explanations outside the JSON. JSON only.
"""


class DecisionAgent:
    def __init__(self, client):
        self.client = client

    def decide(self, state, memory):
        response = self.client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": DECISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"""
Mission
{memory.mission}

Current Objective
{memory.objective}

Current State
{json.dumps(state)}

Action History
{json.dumps(memory.history[-8:])}

Return one JSON action.
""",
                },
            ],
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
        return {"action": "wait", "ms": 2000, "why": "fallback: could not parse decision"}


def make_decision_policy(client, game_id: str = None):
    """Return the active decision policy.

    If config.USE_RL_POLICY is set and a trained Q-table exists for the game,
    return an RLDecisionAgent (a policy learned offline from the MapStore graph)
    with the LLM DecisionAgent as its off-policy fallback — a hybrid learned+LLM
    controller. Otherwise return the plain LLM DecisionAgent. Both expose the
    same .decide(state, memory) contract, so callers don't change.

    See REINFORCEMENT_LEARNING.md for the design.
    """
    import os
    import src.core.config as config

    llm_agent = DecisionAgent(client)
    if not getattr(config, "USE_RL_POLICY", False):
        return llm_agent

    if not game_id:
        from src.core.active_game import GAME
        game_id = GAME.game_id
    policy_path = config.RL_POLICY_FILE or f"outputs/rl/{game_id}_qtable.json"
    if not os.path.exists(policy_path):
        print(f"⚠ USE_RL_POLICY set but no Q-table at {policy_path} -- "
              f"falling back to the LLM DecisionAgent. Train one with "
              f"`python -m src.rl.train --game {game_id}`.")
        return llm_agent

    try:
        from src.rl.rl_decision_agent import RLDecisionAgent
        return RLDecisionAgent.from_files(
            game_id, policy_path=policy_path, fallback=llm_agent)
    except Exception as e:
        print(f"⚠ could not load RL policy ({e}); using the LLM DecisionAgent.")
        return llm_agent