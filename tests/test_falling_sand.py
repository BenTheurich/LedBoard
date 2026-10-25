import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from falling_sand import DRAIN, DROP_AREAS, FULL_STEPS, FallingSand, HEIGHT, SPOUTS, STEP, WIDTH


class FallingSandTests(unittest.TestCase):
    def test_starts_empty_and_randomizes_positions_and_drop_area(self):
        effect = FallingSand()
        image = effect.render(0, 0)
        self.assertEqual(image.size, (64, 16))
        self.assertEqual(image.mode, "1")
        self.assertIsNone(image.getbbox())
        self.assertEqual(effect.grains, 0)
        self.assertEqual(SPOUTS[1] - SPOUTS[0], SPOUTS[2] - SPOUTS[1])
        positions = set()
        counts = [0, 0, 0]
        for step in range(90):
            effect.render((step + 1) * STEP, STEP)
            lit_inlets = {x for x, value in enumerate(effect.grid[:WIDTH]) if value}
            self.assertEqual(len(lit_inlets), 1)
            x = lit_inlets.pop()
            positions.add(x)
            self.assertIn(x, sum(DROP_AREAS, ()))
            counts[next(index for index, area in enumerate(DROP_AREAS) if x in area)] += 1
            self.assertEqual(effect.grains, step + 1)
            self.assertEqual(effect.phase, "fill")
        self.assertGreater(len(positions), len(SPOUTS))
        self.assertTrue(all(counts))
        self.assertGreater(len(set(counts)), 1)

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

    def test_backed_up_drop_areas_overflow_until_the_corners_are_full(self):
        effect = FallingSand()
        effect.grid[:] = bytes([1]) * (WIDTH * HEIGHT)
        for y in range(HEIGHT):
            effect.grid[y * WIDTH] = 0
        effect.grains = sum(effect.grid)
        for step in range(HEIGHT):
            image = effect.render((step + 1) * STEP, STEP)
            self.assertEqual(effect.grains, WIDTH * HEIGHT - HEIGHT + step + 1)
            self.assertEqual(effect.grains, sum(effect.grid))
            self.assertEqual(effect.phase, "full" if step == HEIGHT - 1 else "fill")
        self.assertEqual(image.tobytes(), bytes([255]) * (WIDTH * HEIGHT // 8))

    def test_fully_lit_image_is_visible_before_the_central_plug_opens(self):
        effect = FallingSand()
        effect.grid[:] = bytes([1]) * (WIDTH * HEIGHT)
        effect.grains = WIDTH * HEIGHT
        image = effect.render(STEP, STEP)
        self.assertEqual(effect.phase, "full")
        self.assertEqual(image.tobytes(), bytes([255]) * (WIDTH * HEIGHT // 8))
        for step in range(FULL_STEPS - 1):
            effect.render((step + 2) * STEP, STEP)
            self.assertEqual(effect.phase, "full")
            self.assertEqual(effect.grains, WIDTH * HEIGHT)
        effect.render((FULL_STEPS + 1) * STEP, STEP)
        self.assertEqual(effect.phase, "drain")
        self.assertTrue(all(not effect.grid[(HEIGHT - 1) * WIDTH + x] for x in DRAIN))
        self.assertEqual(effect.grid[-WIDTH], 1)
        self.assertEqual(effect.grid[-1], 1)
        self.assertEqual(effect.grains, WIDTH * HEIGHT - len(DRAIN))

    def test_delayed_frame_cannot_skip_the_fully_lit_image(self):
        effect = FallingSand()
        effect.grid[:] = bytes([1]) * (WIDTH * HEIGHT)
        effect.grid[0] = 0
        effect.grains = WIDTH * HEIGHT - 1
        image = effect.render(STEP * 6, STEP * 6)
        self.assertEqual(effect.phase, "full")
        self.assertEqual(image.tobytes(), bytes([255]) * (WIDTH * HEIGHT // 8))

    def test_open_plug_funnels_floor_grains_and_keeps_new_sand_falling(self):
        effect = FallingSand()
        for x, y in ((0, 15), (63, 15), (0, 8), (28, 14), (31, 15)):
            effect.grid[y * WIDTH + x] = 1
        effect.grains = 5
        effect._open_drain()
        image = effect.render(STEP, STEP)
        self.assertEqual(effect.grid[9 * WIDTH], 1)
        self.assertEqual(effect.grid[15 * WIDTH + 1], 1)
        self.assertEqual(effect.grid[15 * WIDTH + 62], 1)
        self.assertTrue(all(not effect.grid[(HEIGHT - 1) * WIDTH + x] for x in DRAIN))
        self.assertEqual(effect._draining_grains, 3)
        self.assertEqual(effect.grid[:WIDTH].count(2), 1)
        self.assertEqual(effect.grains, 4)
        self.assertEqual(sum(bool(pixel) for pixel in image.getdata()), 4)
        for step in range(200):
            effect.render((step + 2) * STEP, STEP)
            self.assertEqual(effect.grains, WIDTH * HEIGHT - effect.grid.count(0))
            if effect.completed_cycles:
                break
        self.assertEqual(effect.completed_cycles, 1)
        self.assertEqual(effect.phase, "fill")
        self.assertEqual(effect._draining_grains, 0)
        self.assertGreater(effect.grains, 0)
        # Once plugged, grains at the outlet accumulate instead of escaping.
        outlet = (HEIGHT - 1) * WIDTH + WIDTH // 2
        if not effect.grid[outlet]:
            effect.grid[outlet] = 1
            effect.grains += 1
        before = effect.grains
        effect.render(0, STEP)
        self.assertTrue(effect.grid[outlet])
        self.assertEqual(effect.grains, before + 1)

    def test_repeated_full_fill_and_plug_cycles_do_not_stall_or_lose_counts(self):
        effect = FallingSand(seed=7)
        phases = set()
        saw_fill_after_drain = False
        full_cycles = set()
        for step in range(4000):
            image = effect.render((step + 1) * STEP, STEP)
            phases.add(effect.phase)
            self.assertEqual(len(effect.grid), WIDTH * HEIGHT)
            self.assertEqual(effect.grains, WIDTH * HEIGHT - effect.grid.count(0))
            self.assertLessEqual(effect.grains, WIDTH * HEIGHT)
            self.assertEqual(effect.gravity, 1)
            if effect.phase == "drain":
                self.assertEqual(effect._draining_grains, effect.grid.count(1))
                self.assertTrue(all(not effect.grid[(HEIGHT - 1) * WIDTH + x] for x in DRAIN))
            if effect.phase == "full":
                full_cycles.add(effect.completed_cycles)
                self.assertEqual(effect.grains, WIDTH * HEIGHT)
                self.assertEqual(image.tobytes(), bytes([255]) * (WIDTH * HEIGHT // 8))
            if effect.completed_cycles and effect.phase == "fill":
                saw_fill_after_drain = True
                self.assertEqual(effect._draining_grains, 0)
                self.assertGreater(effect.grains, 0)
            if effect.completed_cycles >= 2:
                break
        self.assertEqual(phases, {"fill", "full", "drain"})
        self.assertEqual(full_cycles, {0, 1})
        self.assertEqual(effect.completed_cycles, 2)
        self.assertTrue(saw_fill_after_drain)

    def test_long_pause_has_bounded_catch_up_work(self):
        effect = FallingSand()
        effect.render(1000, 1000)
        self.assertEqual(effect.steps, 6)
        self.assertEqual(effect.grains, 6)
        self.assertEqual(effect.phase, "fill")


if __name__ == "__main__":
    unittest.main()
