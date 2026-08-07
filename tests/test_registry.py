"""
test_registry.py — the game plugin registry works and Bloons is registered
as a well-formed GameProfile. Device-free; run with:

    python -m pytest tests/test_registry.py -v
"""

import unittest

from src.games.base import GameProfile
from src.games.registry import available_games, get_game


class TestRegistry(unittest.TestCase):
    def test_bloons_is_discovered(self):
        self.assertIn("bloons_td6", available_games())

    def test_get_game_returns_profile_instance(self):
        game = get_game("bloons_td6")
        self.assertIsInstance(game, GameProfile)
        self.assertEqual(game.game_id, "bloons_td6")
        self.assertEqual(game.display_name, "Bloons TD 6")

    def test_identity_matches_config(self):
        import src.core.config as config
        game = get_game("bloons_td6")
        self.assertEqual(game.package, config.GAME_PACKAGE)

    def test_requirements_nonempty(self):
        game = get_game("bloons_td6")
        reqs = game.build_requirements()
        self.assertTrue(reqs)
        # every requirement targets a scene the game declares (no drift)
        for r in reqs:
            target = getattr(r, "target_screen", None)
            if target:
                self.assertIn(
                    target, game.scene_vocabulary,
                    f"requirement {getattr(r, 'requirement_id', '?')} targets "
                    f"'{target}' which is not in scene_vocabulary",
                )

    def test_element_descriptions_present(self):
        game = get_game("bloons_td6")
        desc = game.element_descriptions()
        self.assertIn("dart", desc)
        self.assertIn("grass", desc)

    def test_unknown_game_raises(self):
        with self.assertRaises(KeyError):
            get_game("does_not_exist")

    def test_active_game_resolves(self):
        from src.core.active_game import GAME
        self.assertEqual(GAME.game_id, "bloons_td6")

    def test_validate_passes_for_bloons(self):
        from src.games.validate import validate
        self.assertEqual(validate("bloons_td6"), 0)

    def test_validate_fails_for_unknown(self):
        from src.games.validate import validate
        self.assertEqual(validate("does_not_exist"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
