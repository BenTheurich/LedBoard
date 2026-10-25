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
    def test_rendering_uses_centered_fixed_width_digit_cells(self):
        font = proportional(CP437_FONT)
        # CP437's widest proportional digit is 8 pixels; colons occupy 3.
        self.assertEqual(max(textsize(digit, font)[0] for digit in "0123456789"), 8)
        self.assertEqual(textsize(":", font)[0], 3)
        positions = (5, 13, 21, 24, 32, 40, 43, 51)
        for value in ("00:00:00", "11:11:11", "12:34:56", "23:59:59"):
            with self.subTest(value=value):
                expected = Image.new("1", (64, 8), 0)
                draw = ImageDraw.Draw(expected)
                for character, x in zip(value, positions):
                    text(draw, (x, 0), character, fill="white", font=font)
                expected = expected.resize((64, 16), Image.Resampling.NEAREST)
                image = clock.render_clock_image(value, font)
                self.assertEqual(image.size, (64, 16))
                self.assertEqual(image.tobytes(), expected.tobytes())

    def test_separators_remain_at_the_same_positions_for_narrow_and_wide_times(self):
        font = proportional(CP437_FONT)
        marker = Image.new("1", (3, 8), 0)
        text(ImageDraw.Draw(marker), (0, 0), ":", fill="white", font=font)
        marker = marker.resize((3, 16), Image.Resampling.NEAREST)
        for value in ("00:00:00", "11:11:11", "04:10:40", "23:59:59"):
            with self.subTest(value=value):
                image = clock.render_clock_image(value, font)
                for x in (21, 40):
                    self.assertEqual(image.crop((x, 0, x + 3, 16)).tobytes(), marker.tobytes())

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
