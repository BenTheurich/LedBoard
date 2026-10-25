import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from falling_sand import (CELLS, DRAIN, DRAIN_GROW_STEPS, DRAIN_STEP, DROP_AREAS,
                          FULL_STEPS, FallingSand, HEIGHT, SPOUTS, STEP, WIDTH)


def load_points(effect, points):
    grid = bytearray(CELLS)
    for x, y in points:
        grid[y * WIDTH + x] = 1
    effect.grid = grid


def full_container(effect):
    effect.grid = bytearray([1]) * CELLS


class FallingSandTests(unittest.TestCase):
    def test_empty_start_and_random_positions_within_three_drop_areas(self):
        effect = FallingSand()
        image = effect.render(0, 0)
        self.assertEqual((image.mode, image.size), ('1', (64, 16)))
        self.assertIsNone(image.getbbox())
        self.assertEqual(SPOUTS[1] - SPOUTS[0], SPOUTS[2] - SPOUTS[1])
        positions, counts = set(), [0, 0, 0]
        for step in range(90):
            effect.render((step + 1) * STEP, STEP)
            inlets = {x for x, value in enumerate(effect.grid[:WIDTH]) if value}
            self.assertEqual(len(inlets), 1)
            x = inlets.pop()
            positions.add(x)
            self.assertIn(x, sum(DROP_AREAS, ()))
            counts[next(index for index, area in enumerate(DROP_AREAS) if x in area)] += 1
            self.assertEqual(effect.grains, step + 1)
        self.assertGreater(len(positions), len(SPOUTS))
        self.assertTrue(all(counts))
        self.assertGreater(len(set(counts)), 1)

    def test_packed_image_matches_every_logical_pixel(self):
        effect = FallingSand()
        grid = bytearray(index % 11 in (0, 2, 5) for index in range(CELLS))
        effect.grid = grid
        image = effect.render(0, 0)
        self.assertEqual(list(map(bool, image.getdata())), list(map(bool, grid)))
        self.assertEqual(effect.grains, sum(grid))

    def test_vacancy_propagates_only_one_row_per_tick(self):
        effect = FallingSand()
        grid = bytearray([1]) * CELLS
        grid[(HEIGHT - 1) * WIDTH + 32] = 0
        effect.grid = grid
        effect._move()
        expected = bytearray([1]) * CELLS
        expected[(HEIGHT - 2) * WIDTH + 32] = 0
        self.assertEqual(effect.grid, expected)
        self.assertEqual(effect.grains, CELLS - 1)

    def test_competing_diagonals_do_not_merge_grains(self):
        effect = FallingSand(seed=7)
        load_points(effect, ((20, 4), (22, 4), (19, 5), (20, 5), (22, 5), (23, 5)))
        effect._move()
        grid = effect.grid
        self.assertEqual(effect.grains, 6)
        self.assertEqual(sum(grid), 6)
        self.assertEqual(grid[5 * WIDTH + 21], 1)
        self.assertEqual(grid[4 * WIDTH + 20] + grid[4 * WIDTH + 22], 1)

    def test_edge_grains_cannot_wrap_into_another_row(self):
        for x, neighbor, invalid in ((0, 1, (63, 3)), (63, 62, (0, 5))):
            with self.subTest(edge=x):
                effect = FallingSand()
                load_points(effect, ((x, 3), (x, 4), (neighbor, 4)))
                effect._move()
                grid = effect.grid
                self.assertEqual(grid[3 * WIDTH + x], 1)
                self.assertEqual(grid[invalid[1] * WIDTH + invalid[0]], 0)
                self.assertEqual(sum(grid), 3)

    def test_backed_up_inlets_eventually_fill_every_corner(self):
        effect = FallingSand()
        grid = bytearray([1]) * CELLS
        for y in range(HEIGHT):
            grid[y * WIDTH] = 0
        effect.grid = grid
        for step in range(300):
            image = effect.render((step + 1) * STEP, STEP)
            if effect.grains < CELLS:
                self.assertEqual(effect.phase, 'fill')
            else:
                break
        self.assertEqual(effect.phase, 'full')
        self.assertEqual(image.tobytes(), bytes([255]) * (CELLS // 8))

    def test_full_image_is_visible_even_after_a_delayed_frame(self):
        effect = FallingSand()
        grid = bytearray([1]) * CELLS
        grid[0] = 0
        effect.grid = grid
        image = effect.render(STEP * 6, STEP * 6)
        self.assertEqual(effect.phase, 'full')
        self.assertEqual(image.tobytes(), bytes([255]) * (CELLS // 8))
        for _ in range(FULL_STEPS - 1):
            effect.render(0, STEP)
            self.assertEqual(effect.phase, 'full')
        effect.render(0, STEP)
        self.assertEqual(effect.phase, 'drain')
        self.assertEqual(effect.drain_width, len(DRAIN))

    def test_small_centre_drain_does_not_drag_side_grains(self):
        effect = FallingSand()
        # A supported floor stays put until the opening reaches it.
        load_points(effect, ((x, HEIGHT - 1) for x in range(WIDTH)))
        effect._open_drain()
        effect.render(0, DRAIN_STEP)
        grid = effect.grid
        self.assertEqual(sum(grid), WIDTH - len(DRAIN))
        for x in range(WIDTH):
            self.assertEqual(grid[(HEIGHT - 1) * WIDTH + x], int(x not in DRAIN))
        self.assertIsNone(effect.render(0, 0).crop((0, 0, WIDTH, 1)).getbbox())

    def test_drain_widens_symmetrically_to_the_whole_bottom_then_closes(self):
        effect = FallingSand()
        full_container(effect)
        effect._open_drain()
        widths, previous = set(), CELLS
        for step in range(DRAIN_GROW_STEPS * (WIDTH // 2) + HEIGHT * 3):
            image = effect.render(step * DRAIN_STEP, DRAIN_STEP)
            if effect.phase == 'drain':
                width = effect.drain_width
                widths.add(width)
                self.assertEqual(width % 2, 0)
                start = (WIDTH - width) // 2
                self.assertEqual((effect._outlet >> ((HEIGHT - 1) * WIDTH)).bit_count(), width)
                self.assertEqual(effect._outlet >> ((HEIGHT - 1) * WIDTH), ((1 << width) - 1) << start)
                self.assertLessEqual(effect.grains, previous)
                previous = effect.grains
            else:
                break
        # The last widening step may empty the final corner grains immediately.
        self.assertEqual(effect._drain_radius * 2, WIDTH)
        self.assertIn(2, widths)
        self.assertIn(WIDTH - 2, widths)
        self.assertEqual(effect.phase, 'fill')
        self.assertEqual(effect.completed_cycles, 1)
        self.assertEqual(effect.grains, 0)
        self.assertEqual(effect.drain_width, 0)
        self.assertIsNone(image.getbbox())
        # The newly plugged floor holds grains again.
        load_points(effect, ((WIDTH // 2, HEIGHT - 1),))
        effect.render(0, STEP)
        self.assertEqual(effect.grains, 2)
        self.assertEqual(effect.grid[(HEIGHT - 1) * WIDTH + WIDTH // 2], 1)

    def test_frame_rate_does_not_change_drain_tempo(self):
        states = []
        for fps in (20, 40):
            effect = FallingSand(seed=7)
            full_container(effect)
            effect._open_drain()
            for frame in range(fps * 3):
                image = effect.render((frame + 1) / fps, 1 / fps)
            states.append((image.tobytes(), effect.grains, effect.drain_width, effect.steps))
        self.assertEqual(states[0], states[1])

    def test_repeated_fill_and_empty_cycles_preserve_mass_and_pause_pouring(self):
        effect = FallingSand(seed=7)
        full_cycles = set()
        previous_phase, previous_grains = None, 0
        empty_images = 0
        for frame in range(8000):
            image = effect.render((frame + 1) / 20, 1 / 20)
            lit = sum(byte.bit_count() for byte in image.tobytes())
            self.assertEqual(lit, effect.grains)
            self.assertLessEqual(effect.grains, CELLS)
            self.assertEqual(effect.gravity, 1)
            if effect.phase == 'full':
                full_cycles.add(effect.completed_cycles)
                self.assertEqual(effect.grains, CELLS)
            if previous_phase == effect.phase == 'drain':
                self.assertLessEqual(effect.grains, previous_grains)
            if previous_phase == 'drain' and effect.phase == 'fill':
                empty_images += 1
                self.assertEqual(effect.grains, 0)
                self.assertIsNone(image.getbbox())
            previous_phase, previous_grains = effect.phase, effect.grains
            if effect.completed_cycles == 2:
                break
        self.assertEqual(full_cycles, {0, 1})
        self.assertEqual(empty_images, 2)
        self.assertEqual(effect.completed_cycles, 2)

    def test_pause_catch_up_is_bounded_in_both_phases(self):
        for drain in (False, True):
            with self.subTest(drain=drain):
                effect = FallingSand()
                if drain:
                    full_container(effect)
                    effect._open_drain()
                effect.render(1000, 1000)
                self.assertEqual(effect.steps, 6)


if __name__ == '__main__':
    unittest.main()
