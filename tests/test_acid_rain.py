from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from acid_rain import AcidRain, DROP_COUNT, MAX_SPLASHES


class AcidRainTests(unittest.TestCase):
    def test_monochrome_output_is_visible_and_evolves(self):
        effect = AcidRain()
        first = effect.render(0, 0)
        self.assertEqual(first.mode, "1")
        self.assertEqual(first.size, (64, 16))
        self.assertIsNotNone(first.getbbox())
        later = effect.render(0.75, 0.75)
        self.assertIsNotNone(later.getbbox())
        self.assertNotEqual(first.tobytes(), later.tobytes())

    def test_tempo_does_not_depend_on_render_rate(self):
        frames = []
        for fps in (20, 40):
            effect = AcidRain(seed=90)
            for step in range(fps * 2):
                frame = effect.render((step + 1) / fps, 1 / fps)
            frames.append(frame.tobytes())
        self.assertEqual(frames[0], frames[1])

    def test_streams_recycle_and_residue_stays_bounded(self):
        effect = AcidRain(seed=7219)
        previous = [drop.y for drop in effect.drops]
        resets = 0
        saw_splash = False
        for step in range(1200):
            image = effect.render((step + 1) / 20, 1 / 20)
            resets += sum(drop.y < old for drop, old in zip(effect.drops, previous))
            previous = [drop.y for drop in effect.drops]
            saw_splash |= bool(effect.splashes)
            self.assertEqual(len(effect.drops), DROP_COUNT)
            self.assertLessEqual(len(effect.splashes), MAX_SPLASHES)
            self.assertTrue(all(splash.age < splash.lifetime for splash in effect.splashes))
        self.assertGreater(resets, DROP_COUNT * 5)
        self.assertTrue(saw_splash)
        self.assertIsNotNone(image.getbbox())

    def test_a_long_pause_does_not_fast_forward_the_streams(self):
        effect = AcidRain()
        before = [drop.y for drop in effect.drops]
        effect.render(1000, 1000)
        self.assertTrue(all(0 <= drop.y - old <= 3.51
                            for drop, old in zip(effect.drops, before)))


if __name__ == "__main__":
    unittest.main()
