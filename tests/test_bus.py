from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import my_bus_script3 as bus


class BusScrollTests(unittest.TestCase):
    def observed_scroll(self, count):
        held_pairs = []
        offsets = []
        image = Image.new("1", (64, max(2, count) * 8))

        def show(_, offset):
            offsets.append(offset)

        def sleep(seconds):
            if seconds == bus.PAUSE_AT_ROWS:
                offset = offsets[-1]
                self.assertEqual(offset % 8, 0)
                held_pairs.append((offset // 8 + 1, offset // 8 + 2))
            else:
                self.assertEqual(seconds, bus.SCROLL_SPEED)

        with patch.object(bus, "create_tall_scroll_image", return_value=(image, image.height)), \
                patch.object(bus, "show_window", side_effect=show), \
                patch.object(bus.time, "sleep", side_effect=sleep):
            bus.run_vertical_scroll([("230:", "5m")] * count)
        self.assertEqual(offsets[0], 0)
        self.assertEqual(offsets[-1], 0)
        self.assertTrue(all(0 <= offset <= image.height - 16 for offset in offsets))
        return held_pairs

    def test_middle_pair_pauses_on_the_way_down_and_back_up(self):
        self.assertEqual(self.observed_scroll(4), [(1, 2), (2, 3), (3, 4), (2, 3)])

    def test_long_list_holds_every_pair_without_repeating_the_endpoints(self):
        held = self.observed_scroll(8)
        self.assertEqual(held[:7], [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8)])
        self.assertEqual(held[7:], [(6, 7), (5, 6), (4, 5), (3, 4), (2, 3)])

    def test_short_or_empty_lists_hold_one_still_page(self):
        for count in (0, 1, 2):
            with self.subTest(count=count):
                self.assertEqual(self.observed_scroll(count), [(1, 2)])

    def test_single_departure_padding_does_not_change_the_input_list(self):
        departures = [("230:", "5m")]
        image, height = bus.create_tall_scroll_image(departures)
        self.assertEqual(departures, [("230:", "5m")])
        self.assertEqual((image.size, height), ((64, 16), 16))
        self.assertIsNotNone(image.crop((0, 0, 64, 8)).getbbox())
        self.assertIsNone(image.crop((0, 8, 64, 16)).getbbox())


if __name__ == "__main__":
    unittest.main()
