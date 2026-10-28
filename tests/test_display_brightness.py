from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from display_brightness import brightness_for_time


class BrightnessTests(unittest.TestCase):
    def test_original_bus_schedule_at_day_and_night_boundaries(self):
        for time, expected in (("00:00:00", 10), ("06:59:59", 10),
                               ("07:00:00", 32), ("19:59:59", 32),
                               ("20:00:00", 10), ("23:59:59", 10)):
            with self.subTest(time=time):
                now = datetime.fromisoformat(f"2026-10-28T{time}")
                self.assertEqual(brightness_for_time(now), expected)
