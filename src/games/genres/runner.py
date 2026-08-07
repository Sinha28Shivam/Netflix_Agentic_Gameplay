"""
src/games/genres/runner.py — RunnerMixin.

Genre support for endless runners (Subway Surfers, Temple Run, …): a real-time
"grab frame → perceive → decide → act" control loop over the fast-I/O backend
(src/device/fast_io.py), plus a pure rule-based dodge policy.

Modeled on MultiplayerMixin (src/games/genres/pvp.py): a runner's track is
procedurally generated, so ``nondeterministic = True`` — QA asserts on
outcomes/invariants (distance survived, a swipe changed lane) rather than
replaying an exact recorded route.

A concrete runner supplies ``perceive(frame) -> LaneState``; the mixin provides
the loop and a default ``decide(LaneState) -> action`` the game may override.
``decide`` is a pure function of the perception output, so it is fully unit-
testable without a device.
"""

import time
from typing import Any, Callable, Optional


# Action vocabulary the loop dispatches through FastControl.
ACTIONS = ("left", "right", "jump", "roll", None)


class RunnerMixin:
    genre = "runner"
    nondeterministic = True

    # Loop tuning (override per game).
    tick_hz = 15                 # perception/decision cadence
    max_run_seconds = 180        # hard cap on a single run
    stale_seconds = 1.5          # frames unchanged this long => run ended (crash/pause)
    _stale_pixel_eps = 3.0       # mean abs frame diff below this = "no motion"

    # ---- perception hook: a concrete runner MUST implement this -------------
    def perceive(self, frame) -> Any:
        raise NotImplementedError("Runner games must implement perceive(frame) -> LaneState")

    # ---- decision policy (pure; override to customize) ----------------------
    def decide(self, state) -> Optional[str]:
        """Rule-based dodge policy over a LaneState. Returns an action or None."""
        lane = getattr(state, "player_lane", 1)
        blocked = getattr(state, "blocked", [False, False, False])

        if blocked[lane]:
            # Prefer to pass the obstacle in-lane if it's roll/jump-able.
            if getattr(state, "low_obstacle", False):
                return "roll"
            if getattr(state, "high_obstacle", False):
                return "jump"
            # Otherwise switch to the nearest clear lane (prefer adjacent).
            clear = [i for i, b in enumerate(blocked) if not b]
            if clear:
                target = min(clear, key=lambda l: (abs(l - lane), l))
                return "left" if target < lane else "right"
            return "jump"  # boxed in — hail-mary hop

        # Current lane clear: drift toward coins if that lane is also clear.
        coins = getattr(state, "coins_lane", None)
        if coins is not None and coins != lane and not blocked[coins]:
            return "left" if coins < lane else "right"
        return None

    # ---- run-ended detection (override for a game-specific game-over) -------
    def run_ended(self, state, frame) -> bool:
        return False

    def on_crash(self) -> None:
        return None

    # ---- the real-time control loop ----------------------------------------
    def run_until_crash(self, source, control,
                        max_seconds: Optional[int] = None,
                        on_action: Optional[Callable[[str], None]] = None) -> dict:
        """Drive the run until it ends. ``source``/``control`` are a FrameSource
        and FastControl (see fast_io.get_fast_io). Returns run stats."""
        import numpy as np

        deadline = time.time() + (max_seconds or self.max_run_seconds)
        period = 1.0 / max(1, self.tick_hz)
        actions = {"left": 0, "right": 0, "jump": 0, "roll": 0}
        ticks = 0
        started = time.time()
        prev_small = None
        stale_since = None
        w = h = None
        ended_reason = "deadline"

        while time.time() < deadline:
            t0 = time.time()
            frame = source.read()
            if frame is None:
                time.sleep(period)
                continue
            if w is None:
                h, w = frame.shape[:2]

            # motion / stall detection -> run ended (crash, pause, or game-over)
            small = np.asarray(frame[::16, ::16], dtype=np.int16)
            if prev_small is not None and small.shape == prev_small.shape:
                if float(np.abs(small - prev_small).mean()) < self._stale_pixel_eps:
                    stale_since = stale_since or t0
                    if t0 - stale_since >= self.stale_seconds:
                        ended_reason = "stalled"
                        break
                else:
                    stale_since = None
            prev_small = small

            state = self.perceive(frame)
            if self.run_ended(state, frame):
                ended_reason = "run_ended"
                break

            action = self.decide(state)
            if action:
                self._dispatch(control, action, w, h)
                actions[action] += 1
                if on_action:
                    on_action(action)

            ticks += 1
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)

        if ended_reason in ("stalled", "run_ended"):
            self.on_crash()

        return {
            "duration": round(time.time() - started, 2),
            "ticks": ticks,
            "actions": actions,
            "ended_reason": ended_reason,
        }

    @staticmethod
    def _dispatch(control, action, w, h):
        if action == "left":
            control.lane_left(w, h)
        elif action == "right":
            control.lane_right(w, h)
        elif action == "jump":
            control.jump(w, h)
        elif action == "roll":
            control.roll(w, h)
