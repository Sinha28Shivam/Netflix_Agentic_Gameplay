"""
src/games/genres/tower_defense.py — TowerDefenseMixin.

Carries the mechanics common to tower-defense games (an economy loop, unit
placement, a resource/round HUD) that are NOT universal to all games. A TD
game mixes this into its GameProfile and fills in the roster.

Phase 1 scope: this mix-in exposes the economy CONSTANTS (currently sourced
from config so Bloons behavior is byte-identical) and the genre tag. The heavy
mechanics — the ``play()`` economy loop, ``place_one()`` press-hold-drag, and
red-tile invalid detection — still live in the engine/executor today; they move
into this mix-in in Phase 3 (behind golden tests) without changing behavior.
"""

import src.core.config as config


class TowerDefenseMixin:
    genre = "tower_defense"

    # Economy constants. Sourced from config for now so nothing about the
    # current Bloons run changes; a TD game overrides these class attributes.
    @property
    def cheapest_unit_cost(self) -> int:
        return config.DART_COST

    @property
    def cash_reserve(self) -> int:
        return config.CASH_RESERVE

    @property
    def max_units(self) -> int:
        return config.MAX_MONKEYS
