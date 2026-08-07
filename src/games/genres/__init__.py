"""
src/games/genres — reusable genre mix-ins.

A game combines a genre mix-in with GameProfile to inherit mechanics that are
shared within a genre but are NOT universal (so they don't belong on the base):

    class BloonsTD6(TowerDefenseMixin, GameProfile): ...

Mix-ins are composable — a multiplayer tower-defense game would be
``class Foo(TowerDefenseMixin, MultiplayerMixin, GameProfile)``.
"""
