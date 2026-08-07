"""
src/games/genres/pvp.py — MultiplayerMixin.

Support for automating ONE client of a multiplayer / PvP game on a single
device: matchmaking waits, opponent-presence and match-end detection, and a
connection-loss recovery hook. Because a live opponent makes the screen flow
non-deterministic, ``nondeterministic = True`` signals the planner/test-runner
to assert on OUTCOMES and INVARIANTS (match joined, a legal state change
happened, match resolved) instead of replaying an exact recorded route.

Two-device / two-client orchestration (two synchronized players) is a separate,
advanced capability — see ``src/device/session.py`` (DeviceSession).
"""

import time


class MultiplayerMixin:
    genre = "multiplayer"

    # Tell the deterministic planner/runner not to expect an exact screen graph.
    nondeterministic = True
    matchmaking_timeout = 60          # seconds to wait for an opponent
    _poll_interval = 2                # seconds between matchmaking polls

    def wait_for_match(self, timeout: int = None) -> bool:
        """Poll until the match actually starts. Returns True if a match began
        before ``timeout``. Handles matchmaking delay / network latency."""
        from src.core import qa_common

        timeout = timeout or self.matchmaking_timeout
        png = "outputs/logs/current.png"
        for _ in range(max(1, int(timeout / max(1, self._poll_interval)))):
            qa_common.screencap(png)
            if self.match_started(png):
                return True
            time.sleep(self._poll_interval)
        return False

    # ---- override these for your game -------------------------------------
    def match_started(self, png: str) -> bool:
        """True once the live match screen is up (override for your game)."""
        return False

    def opponent_present(self, state: dict) -> bool:
        """True if an opponent is detected in the observed state."""
        return False

    def match_ended(self, state: dict) -> bool:
        """True when the match has resolved (default: a victory/defeat scene)."""
        return state.get("scene") in ("victory", "defeat")

    def on_connection_lost(self) -> None:
        """Recovery hook when the network connection drops mid-match. Default is
        a no-op; wire game-specific reconnect handling here (the RecoveryAgent
        stuck-loop path calls into the active game)."""
        return None
