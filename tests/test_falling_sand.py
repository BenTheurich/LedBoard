import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from falling_sand import FallingSand, HEIGHT, SPOUTS, STEP, WIDTH


class FallingSandTests(unittest.TestCase):
    def test_starts_empty_and_emits_only_at_three_fixed_even_spouts(self):
        effect = FallingSand()
        image = effect.render(0, 0)
        self.assertEqual(image.size, (64, 16))
        self.assertEqual(image.mode, "1")
        self.assertIsNone(image.getbbox())
        self.assertEqual(effect.grains, 0)
        self.assertEqual(SPOUTS[1] - SPOUTS[0], SPOUTS[2] - SPOUTS[1])
        for step in range(9):
            effect.render((step + 1) * STEP, STEP)
            lit_inlets = {x for x, value in enumerate(effect.grid[:WIDTH]) if value}
            self.assertEqual(lit_inlets, {SPOUTS[step % 3]})
            self.assertEqual(effect.grains, step + 1)
            self.assertEqual(effect.phase, "fill")

    def test_falling_grains_move_down_and_floor_grains_stay_in_place(self):
        effect = FallingSand(seed=7)
        effect.grid[8 * WIDTH + 32] = 1
        effect.grid[15 * WIDTH + 20] = 1
        effect.grid[14 * WIDTH + 20] = 1
        effect.grains = 3
        effect.render(STEP, STEP)
        self.assertEqual(effect.gravity, 1)
        self.assertEqual(effect.grid[8 * WIDTH + 32], 0)
        self.assertEqual(effect.grid[9 * WIDTH + 32], 1)
        self.assertEqual(effect.grid[15 * WIDTH + 20], 1)
        self.assertEqual(effect.grid[14 * WIDTH + 20], 0)
        self.assertEqual(effect.grid[15 * WIDTH + 19] + effect.grid[15 * WIDTH + 21], 1)
        self.assertEqual(effect.grains, sum(effect.grid))

    def test_inlet_grains_that_can_fall_do_not_trigger_premature_drain(self):
        effect = FallingSand()
        for x in SPOUTS:
            effect.grid[x] = 1
        effect.grains = 3
        effect.render(STEP, STEP)
        self.assertEqual(effect.phase, "fill")
        self.assertEqual(effect.completed_cycles, 0)
        for x in SPOUTS:
            self.assertEqual(effect.grid[WIDTH + x], 1)

    def test_blocked_inlets_start_a_cohesive_slide_after_movement(self):
        effect = FallingSand()
        effect.grid[:] = bytes([1]) * (WIDTH * HEIGHT)
        effect.grains = WIDTH * HEIGHT
        effect.render(STEP, STEP)
        self.assertEqual(effect.phase, "drain")
        self.assertEqual(effect.grid[:WIDTH].count(1), 1)
        self.assertEqual(effect.grid[SPOUTS[0]], 1)
        self.assertEqual(effect.grid[WIDTH:], bytes([1]) * (WIDTH * (HEIGHT - 1)))
        self.assertEqual(effect.grains, WIDTH * (HEIGHT - 1) + 1)

    def test_drain_translates_the_whole_image_and_keeps_streams_running(self):
        effect = FallingSand()
        effect.grid[:] = bytes((x + y) % 2 for y in range(HEIGHT) for x in range(WIDTH))
        effect.grains = sum(effect.grid)
        effect.phase = "drain"
        for step in range(HEIGHT):
            before = bytes(effect.grid)
            expected = bytearray(bytes(WIDTH) + before[:-WIDTH])
            expected[SPOUTS[step % 3]] = 1
            effect.render((step + 1) * STEP, STEP)
            self.assertEqual(effect.grid, expected)
            self.assertEqual(effect.grains, sum(effect.grid))
            self.assertEqual(effect.gravity, 1)
        self.assertEqual(effect.completed_cycles, 1)
        self.assertEqual(effect.phase, "fill")
        self.assertEqual(effect.grains, HEIGHT)
        effect.render((HEIGHT + 1) * STEP, STEP)
        self.assertEqual(effect.grains, HEIGHT + 1)

    def test_repeated_fill_and_slide_cycles_do_not_stall_or_lose_counts(self):
        effect = FallingSand(seed=7)
        phases = set()
        saw_fill_after_slide = False
        for step in range(6000):
            effect.render((step + 1) * STEP, STEP)
            phases.add(effect.phase)
            self.assertEqual(len(effect.grid), WIDTH * HEIGHT)
            self.assertEqual(effect.grains, sum(effect.grid))
            self.assertLessEqual(effect.grains, WIDTH * HEIGHT)
            self.assertEqual(effect.gravity, 1)
            if effect.completed_cycles and effect.phase == "fill":
                saw_fill_after_slide = True
                self.assertGreater(effect.grains, 0)
            if effect.completed_cycles >= 3:
                break
        self.assertEqual(phases, {"fill", "drain"})
        self.assertGreaterEqual(effect.completed_cycles, 3)
        self.assertTrue(saw_fill_after_slide)

    def test_long_pause_has_bounded_catch_up_work(self):
        effect = FallingSand()
        effect.render(1000, 1000)
        self.assertEqual(effect.steps, 6)
        self.assertEqual(effect.grains, 6)
        self.assertEqual(effect.phase, "fill")


if __name__ == "__main__":
    unittest.main()
