from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentMemory:
    mission: str = "Reach Round 10 on Monkey Meadow"
    objective: str = "Launch Game"
    scene: str = "unknown"
    previous_scene: str = "unknown"
    confidence: float = 0.0

    history: List[Dict] = field(default_factory=list)
    visited_scenes: List[str] = field(default_factory=list)

    recovery_attempts: int = 0
    same_scene_count: int = 0
    last_action: Optional[Dict] = None

    def update_scene(self, state: Dict[str, Any]):
        self.previous_scene = self.scene
        self.scene = state.get("scene", "unknown")
        self.confidence = state.get("confidence", 0.0)

        if self.scene == self.previous_scene:
            self.same_scene_count += 1
        else:
            self.same_scene_count = 0

        if self.scene not in self.visited_scenes:
            self.visited_scenes.append(self.scene)

    def log_decision(self, decision: Dict):
        self.last_action = decision
        self.history.append({"scene": self.scene, "decision": decision})
        if len(self.history) > 50:
            self.history.pop(0)
