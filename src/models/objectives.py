def update_objective(state, memory):
    """Set memory.objective from the active game's scene->objective map."""
    from src.core.active_game import GAME

    scene = state.get("scene", "unknown")
    memory.objective = GAME.objective_for_scene(scene)
