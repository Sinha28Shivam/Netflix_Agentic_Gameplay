"""
MapStore — the persistent "Map Store" from the architecture diagram.

Holds, per game, a graph of:
  nodes: every distinct screen the Map Agent has ever seen
  edges: every (from_screen --action--> to_screen) transition that worked

This is what makes "new game = setup, not new code" literally true:
config.py no longer hardcodes a single mission. Instead, each game gets
its own map file under maps/<game_id>.json, built once by a guided seed
pass, then read by the Planner and patched by the Orchestrator's own
exploration.

Swap target: this JSON file is a stand-in for the "Map Store" service
in the architecture diagram. The read/write interface below
(load/save/upsert_node/upsert_edge) is the contract — point it at a real
DB later without touching callers.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

MAPS_DIR = os.environ.get("MAPS_DIR", "maps")


@dataclass
class ScreenNode:
    screen_id: str                       # stable id, e.g. "main_menu"
    label: str                           # human label
    first_seen: float
    last_seen: float
    seen_count: int = 1
    sample_ui_texts: List[str] = field(default_factory=list)
    actionable_elements: List[Dict[str, Any]] = field(default_factory=list)
    is_terminal: bool = False            # victory/defeat/crash-type screen
    tags: List[str] = field(default_factory=list)  # e.g. ["compliance_relevant"]


@dataclass
class TransitionEdge:
    from_screen: str
    action: Dict[str, Any]               # {"action":"tap","target":"Play",...}
    to_screen: str
    seen_count: int = 1
    source: str = "seed"                 # "seed" | "explore" | "replay"


class MapStore:
    """One MapStore instance == one game's map."""

    def __init__(self, game_id: str, maps_dir: str = MAPS_DIR):
        self.game_id = game_id
        self.maps_dir = maps_dir
        self.path = os.path.join(maps_dir, f"{game_id}.json")
        self.nodes: Dict[str, ScreenNode] = {}
        self.edges: List[TransitionEdge] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self):
        # Missing, empty, or corrupt map file -> start fresh rather than crash.
        # An interrupted save() (which truncates the file via open(w) before
        # writing) can leave a 0-byte/partial JSON; the Mapper rebuilds and
        # re-saves anyway, so treating it as "no data yet" is the safe behaviour.
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
        except (ValueError, OSError) as e:
            print(f"WARNING: map file {self.path} is empty/corrupt ({e}); "
                  f"starting with an empty map (it will be rebuilt).")
            return
        for node_id, node in data.get("nodes", {}).items():
            self.nodes[node_id] = ScreenNode(**node)
        for edge in data.get("edges", []):
            self.edges.append(TransitionEdge(**edge))

    def save(self):
        os.makedirs(self.maps_dir, exist_ok=True)
        data = {
            "game_id": self.game_id,
            "updated_at": time.time(),
            "nodes": {k: asdict(v) for k, v in self.nodes.items()},
            "edges": [asdict(e) for e in self.edges],
        }
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    # Writes (called by MapAgent during seeding/exploration)
    # ------------------------------------------------------------------
    def upsert_node(
        self,
        screen_id: str,
        label: Optional[str] = None,
        ui_texts: Optional[List[str]] = None,
        actionable_elements: Optional[List[Dict]] = None,
        is_terminal: bool = False,
        tags: Optional[List[str]] = None,
    ) -> ScreenNode:
        now = time.time()
        if screen_id in self.nodes:
            node = self.nodes[screen_id]
            node.last_seen = now
            node.seen_count += 1
            if ui_texts:
                node.sample_ui_texts = ui_texts[:20]
            if actionable_elements:
                node.actionable_elements = actionable_elements
            if tags:
                node.tags = sorted(set(node.tags) | set(tags))
        else:
            node = ScreenNode(
                screen_id=screen_id,
                label=label or screen_id,
                first_seen=now,
                last_seen=now,
                sample_ui_texts=(ui_texts or [])[:20],
                actionable_elements=actionable_elements or [],
                is_terminal=is_terminal,
                tags=tags or [],
            )
            self.nodes[screen_id] = node
        return node

    def upsert_edge(self, from_screen: str, action: Dict, to_screen: str, source: str = "explore"):
        for edge in self.edges:
            if (
                edge.from_screen == from_screen
                and edge.to_screen == to_screen
                and edge.action.get("action") == action.get("action")
                and edge.action.get("target") == action.get("target")
            ):
                edge.seen_count += 1
                return edge
        edge = TransitionEdge(from_screen=from_screen, action=action, to_screen=to_screen, source=source)
        self.edges.append(edge)
        return edge

    # ------------------------------------------------------------------
    # Reads (called by PlannerAgent, Orchestrator, gap-detection)
    # ------------------------------------------------------------------
    def known_screens(self) -> List[str]:
        return list(self.nodes.keys())

    def outgoing(self, screen_id: str) -> List[TransitionEdge]:
        return [e for e in self.edges if e.from_screen == screen_id]

    def path_to(self, target_screen: str, start_screen: str = "main_menu") -> Optional[List[TransitionEdge]]:
        """Breadth-first search over recorded edges — used by the planner to
        turn 'test the upgrade modal' into a concrete navigation sequence."""
        if start_screen == target_screen:
            return []

        frontier = [(start_screen, [])]
        visited = {start_screen}
        while frontier:
            current, path = frontier.pop(0)
            for edge in self.outgoing(current):
                if edge.to_screen in visited:
                    continue
                new_path = path + [edge]
                if edge.to_screen == target_screen:
                    return new_path
                visited.add(edge.to_screen)
                frontier.append((edge.to_screen, new_path))
        return None  # no known route yet — a MapGap for the Remediation agent

    def coverage_summary(self) -> Dict[str, Any]:
        return {
            "game_id": self.game_id,
            "screens_mapped": len(self.nodes),
            "edges_mapped": len(self.edges),
            "terminal_screens": [n.screen_id for n in self.nodes.values() if n.is_terminal],
            "unexplored_targets": [
                n.screen_id for n in self.nodes.values()
                if n.seen_count == 1 and not self.outgoing(n.screen_id)
            ],
        }
 