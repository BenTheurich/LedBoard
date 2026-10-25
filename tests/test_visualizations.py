import random
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from visualizations import AudioSpectrum


class SpectrumTimingTests(unittest.TestCase):
    def state_after_one_second(self, fps):
        random.seed(7219)
        mode = AudioSpectrum()
        for _ in range(fps):
            mode.step(1 / fps)
            mode.draw(ImageDraw.Draw(Image.new("1", (64, 16))))
        return mode.bars, mode.targets, mode.elapsed

    def test_animation_tempo_is_independent_of_render_rate(self):
        slow = self.state_after_one_second(25)
        fast = self.state_after_one_second(50)
        self.assertEqual(slow[:2], fast[:2])
        self.assertAlmostEqual(slow[2], fast[2])

    def test_frames_interpolate_without_advancing_targets(self):
        mode = AudioSpectrum()
        mode.bars = [0] * 32
        mode.targets = [2] * 32
        mode.step(mode.period / 2)
        image = Image.new("1", (64, 16))
        mode.draw(ImageDraw.Draw(image))
        self.assertEqual(image.getbbox(), (0, 15, 64, 16))
        self.assertEqual(mode.bars, [0] * 32)
        self.assertEqual(mode.targets, [2] * 32)


if __name__ == "__main__":
    unittest.main()
