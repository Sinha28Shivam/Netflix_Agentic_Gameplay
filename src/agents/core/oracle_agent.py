class OracleAgent:
    """Gameplay pass/fail verdict for the QA mission."""

    def verify(self, state):
        from src.core.active_game import GAME

        scene = state.get("scene", "unknown")

        if scene == "victory":
            return {"status": "PASS", "reason": "Victory screen reached."}

        if scene == "defeat":
            return {"status": "FAIL", "reason": "Defeat screen reached before target round."}

        if GAME.is_goal_reached(state):
            current_round = (state.get("resources", {}) or {}).get("round")
            return {"status": "PASS", "reason": f"Reached round {current_round}."}

        return {"status": "RUNNING"}
