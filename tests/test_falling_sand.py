import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from falling_sand import FallingSand, HEIGHT, TARGET_GRAINS, WIDTH


class FallingSandTests(unittest.TestCase):
    def test_starts_empty_with_a_short_empty_lead_in(self):
        effect = FallingSand()
        for index in range(11):
            image = effect.render(index * 0.05, 0.05)
            self.assertEqual(image.size, (64, 16))
            self.assertEqual(image.mode, "1")
            self.assertIsNone(image.getbbox())
            self.assertEqual(effect.grains, 0)
            self.assertEqual(effect.phase, "empty")

    def test_repeated_cycles_pour_reverse_and_drain_without_stalling(self):
        effect = FallingSand(seed=7)
        phases = set()
        directions_with_grains = set()
        peak_grains = 0
        saw_empty_after_drain = False
        saw_growth_after_first_cycle = False
        for index in range(1440):
            effect.render(index / 12, 1 / 12)
            phases.add(effect.phase)
            if effect.grains:
                directions_with_grains.add(effect.gravity)
            peak_grains = max(peak_grains, effect.grains)
            self.assertEqual(len(effect.grid), WIDTH * HEIGHT)
            self.assertEqual(sum(effect.grid), effect.grains)
            self.assertLessEqual(effect.grains, TARGET_GRAINS)
            if effect.completed_cycles and effect.phase == "empty":
                self.assertEqual(effect.grains, 0)
                saw_empty_after_drain = True
            if effect.completed_cycles and effect.grains > 0:
                saw_growth_after_first_cycle = True
            if effect.completed_cycles >= 3:
                break
        self.assertGreaterEqual(effect.completed_cycles, 3)
        self.assertEqual(peak_grains, TARGET_GRAINS)
        self.assertEqual(phases, {"empty", "pour", "settle", "reverse_up", "reverse_down", "drain"})
        self.assertEqual(directions_with_grains, {-1, 1})
        self.assertTrue(saw_empty_after_drain)
        self.assertTrue(saw_growth_after_first_cycle)

    def test_gravity_reversal_moves_the_pile_to_the_opposite_edge(self):
        effect = FallingSand(seed=21)
        heights = {}
        for index in range(500):
            previous = effect.phase
            effect.render(index / 12, 1 / 12)
            if previous != effect.phase and effect.grains:
                mean_y = sum((index // WIDTH) * value for index, value in enumerate(effect.grid)) / effect.grains
                if effect.phase == "reverse_down":
                    heights["up"] = mean_y
                elif effect.phase == "drain":
                    heights["down"] = mean_y
                    break
        self.assertLess(heights["up"], HEIGHT / 2)
        self.assertGreater(heights["down"], HEIGHT / 2)

    def test_long_pause_has_bounded_catch_up_work(self):
        effect = FallingSand()
        effect.render(1000, 1000)
        self.assertEqual(effect.phase, "empty")
        self.assertEqual(effect.grains, 0)
        self.assertLessEqual(effect._phase_steps, 6)


if __name__ == "__main__":
    unittest.main()
