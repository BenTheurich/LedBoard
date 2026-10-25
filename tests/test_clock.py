import datetime
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
from luma.core.legacy import text, textsize
from luma.core.legacy.font import CP437_FONT, proportional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import clock


class ClockTests(unittest.TestCase):
    def test_rendering_preserves_original_clock_pixels(self):
        font = proportional(CP437_FONT)
        for value in ("00:00:00", "12:34:56", "23:59:59"):
            width, _ = textsize(value, font)
            tiny = Image.new("1", (width, 8), 0)
            text(ImageDraw.Draw(tiny), (0, 0), value, fill="white", font=font)
            expected = Image.new("1", (64, 16), 0)
            expected.paste(tiny.resize((width, 16), Image.Resampling.NEAREST), ((64 - width) // 2, 0))
            self.assertEqual(clock.render_clock_image(value, font).tobytes(), expected.tobytes())

    def test_duplicate_second_is_not_redrawn_and_sleep_uses_remaining_time(self):
        device = Mock()
        values = [datetime.datetime(2026, 10, 25, 12, 0, 0), datetime.datetime(2026, 10, 25, 12, 0, 0), datetime.datetime(2026, 10, 25, 12, 0, 1)]
        with patch("clock.datetime.datetime") as date, patch("clock.time.time", side_effect=[0.2, 0.9, 1.3]), patch("clock.time.sleep", side_effect=[None, None, KeyboardInterrupt]) as sleep, patch("clock.render_clock_image", return_value=Image.new("1", (64, 16))) as render:
            date.now.side_effect = values
            with self.assertRaises(KeyboardInterrupt):
                clock.run_clock(device, None)
        self.assertEqual(render.call_count, 2)
        self.assertEqual(device.display.call_count, 2)
        for actual, expected in zip(sleep.call_args_list, (0.8, 0.1, 0.7)):
            self.assertAlmostEqual(actual.args[0], expected)


if __name__ == "__main__":
    unittest.main()
