from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from acid_rain import AcidRain, DROP_COUNT, HEIGHT, STEP


class AcidRainTests(unittest.TestCase):
    def test_monochrome_pixels_are_visible_and_evolve(self):
        effect = AcidRain()
        first = effect.render(0, 0)
        self.assertEqual(first.mode, "1")
        self.assertEqual(first.size, (64, 16))
        self.assertIsNotNone(first.getbbox())
        later = effect.render(0.2, 0.2)
        self.assertIsNotNone(later.getbbox())
        self.assertNotEqual(first.tobytes(), later.tobytes())

    def test_each_streak_has_a_pixel_head_and_dotted_single_column_tail(self):
        effect = AcidRain()
        for drop in effect.drops:
            drop.y = -100
        drop = effect.drops[0]
        drop.x, drop.y, drop.length, drop.pattern = 10, 8, 7, 0
        image = effect.render(0, 0)
        pixels = {(x, y) for y in range(16) for x in range(64) if image.getpixel((x, y))}
        self.assertEqual({x for x, _ in pixels}, {10})
        self.assertIn((10, 8), pixels)
        self.assertIn((10, 7), pixels)
        self.assertLess(len(pixels), drop.length)
        self.assertEqual(image.getbbox()[2] - image.getbbox()[0], 1)

    def test_tempo_does_not_depend_on_render_rate(self):
        frames = []
        for fps in (20, 40):
            effect = AcidRain(seed=90)
            for step in range(fps * 2):
                frame = effect.render((step + 1) / fps, 1 / fps)
            frames.append(frame.tobytes())
        self.assertEqual(frames[0], frames[1])

    def test_drops_recycle_with_bounded_state_and_original_speed_range(self):
        effect = AcidRain(seed=7219)
        previous = [drop.y for drop in effect.drops]
        resets = 0
        for step in range(1200):
            image = effect.render((step + 1) / 20, 1 / 20)
            resets += sum(drop.y < old for drop, old in zip(effect.drops, previous))
            previous = [drop.y for drop in effect.drops]
            self.assertEqual(len(effect.drops), DROP_COUNT)
            self.assertTrue(all(6 <= drop.speed <= 14 and 4 <= drop.length <= 7
                                and index * 4 <= drop.x < (index + 1) * 4
                                for index, drop in enumerate(effect.drops)))
        self.assertGreater(resets, DROP_COUNT * 5)
        self.assertIsNotNone(image.getbbox())

    def test_no_pixels_remain_once_tails_pass_below_the_panel(self):
        effect = AcidRain()
        for drop in effect.drops:
            drop.y = HEIGHT + drop.length - 1
        self.assertIsNone(effect.render(0, 0).getbbox())
        # The next update only respawns pixels above the top edge.
        self.assertIsNone(effect.render(STEP, STEP).getbbox())
        self.assertTrue(all(drop.y <= -2 for drop in effect.drops))

    def test_a_long_pause_has_bounded_catchup(self):
        effect = AcidRain()
        before = [drop.y for drop in effect.drops]
        effect.render(1000, 1000)
        self.assertTrue(all(0 <= drop.y - old <= 3.51
                            for drop, old in zip(effect.drops, before)))
        self.assertLess(effect.pending, STEP)


if __name__ == "__main__":
    unittest.main()
