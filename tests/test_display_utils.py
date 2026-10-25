import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from display_utils import FramePacer, map_serpentine


def original_mapping(image):
    physical = Image.new("1", (128, 8), 0)
    draw = ImageDraw.Draw(physical)
    for x in range(64):
        for y in range(16):
            if image.getpixel((x, y)):
                point = (x, y) if y < 8 else (127 - x, 15 - y)
                draw.point(point, fill="white")
    return physical


class MappingTests(unittest.TestCase):
    def test_matches_original_mapping(self):
        random_source = random.Random(7219)
        for density in (0.0, 0.1, 0.5, 1.0):
            with self.subTest(density=density):
                image = Image.new("1", (64, 16), 0)
                image.putdata([int(random_source.random() < density) for _ in range(1024)])
                self.assertEqual(map_serpentine(image).tobytes(), original_mapping(image).tobytes())

    def test_every_logical_pixel_maps_to_its_physical_location(self):
        for x in range(64):
            for y in range(16):
                image = Image.new("1", (64, 16), 0)
                image.putpixel((x, y), 1)
                px, py = (x, y) if y < 8 else (127 - x, 15 - y)
                self.assertEqual(map_serpentine(image).getbbox(), (px, py, px + 1, py + 1))


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FramePacerTests(unittest.TestCase):
    def test_render_time_is_included_in_period(self):
        timer = FakeTime()
        with patch("display_utils.time.monotonic", side_effect=lambda: timer.now), patch("display_utils.time.sleep", side_effect=timer.sleep):
            pacer = FramePacer(25)
            timer.now += 0.01
            pacer.wait()
            self.assertAlmostEqual(timer.now, 0.04)
            timer.now += 0.02
            pacer.wait()
            self.assertAlmostEqual(timer.now, 0.08)
            self.assertAlmostEqual(timer.sleeps[0], 0.03)
            self.assertAlmostEqual(timer.sleeps[1], 0.02)

    def test_overrun_does_not_create_catch_up_burst(self):
        timer = FakeTime()
        with patch("display_utils.time.monotonic", side_effect=lambda: timer.now), patch("display_utils.time.sleep", side_effect=timer.sleep):
            pacer = FramePacer(25)
            timer.now = 0.2
            pacer.wait()
            self.assertEqual(timer.sleeps, [])
            timer.now += 0.005
            pacer.wait()
            self.assertAlmostEqual(timer.sleeps[0], 0.035)


if __name__ == "__main__":
    unittest.main()
