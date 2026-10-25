import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from harmonograph import Harmonograph


class HarmonographTests(unittest.TestCase):
    def test_looping_trace_evolves_with_bounded_history(self):
        mode = Harmonograph()
        first = mode.render(0, 0).tobytes()
        for index in range(1, 601):
            image = mode.render(index / 20, 1 / 20)
            self.assertEqual((image.mode, image.size), ("1", (64, 16)))
            self.assertLessEqual(len(mode.trail), 180)
        self.assertNotEqual(image.tobytes(), first)
        self.assertIsNotNone(image.getbbox())
        self.assertEqual(image.getbbox()[1::2], (0, 16))

    def test_a_pause_does_not_build_a_catch_up_backlog(self):
        mode = Harmonograph()
        mode.render(0, 0)
        mode.render(1000, 1000)
        self.assertLessEqual(len(mode.trail), 9)
        self.assertGreater(mode.next_sample, 1000)
