from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import my_bus_script3 as bus


class BusScrollTests(unittest.TestCase):
    def observed_scroll(self, count, render_seconds=0.0):
        held_pairs = []
        offsets = []
        self.waits = []
        self.display_times = []
        now = [0.0]
        image = Image.new("1", (64, max(2, count) * 8))

        def show(_, offset):
            now[0] += render_seconds
            offsets.append(offset)
            self.display_times.append((offset, now[0]))

        def sleep(seconds):
            self.waits.append((offsets[-1], seconds))
            if seconds == bus.PAUSE_AT_ROWS:
                offset = offsets[-1]
                self.assertEqual(offset % 8, 0)
                held_pairs.append((offset // 8 + 1, offset // 8 + 2))
            else:
                self.assertAlmostEqual(seconds, bus.SCROLL_SPEED - render_seconds)
            now[0] += seconds

        with patch.object(bus, "create_tall_scroll_image", return_value=(image, image.height)), \
                patch.object(bus, "show_window", side_effect=show), \
                patch.object(bus.time, "sleep", side_effect=sleep), \
                patch.object(bus.time, "monotonic", side_effect=lambda: now[0]):
            bus.run_vertical_scroll([("230:", "5m")] * count)
        self.assertEqual(offsets[0], 0)
        self.assertEqual(offsets[-1], 0)
        self.assertTrue(all(0 <= offset <= image.height - 16 for offset in offsets))
        self.offsets = offsets
        return held_pairs

    def test_middle_pair_pauses_when_advancing_through_departures(self):
        self.assertEqual(self.observed_scroll(4), [(1, 2), (2, 3), (3, 4)])

    def test_long_list_holds_every_pair_without_repeating_the_endpoints(self):
        held = self.observed_scroll(8)
        self.assertEqual(held, [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8)])

    def test_return_from_bottom_to_top_is_a_continuous_sweep(self):
        self.observed_scroll(8)
        bottom_frame = self.offsets.index(48)
        self.assertEqual(self.offsets[bottom_frame + 1:], list(range(47, -1, -1)))
        bottom_pause = self.waits.index((48, bus.PAUSE_AT_ROWS))
        return_waits = self.waits[bottom_pause + 1:]
        self.assertEqual([offset for offset, _ in return_waits], list(range(47, 0, -1)))
        for _, delay in return_waits:
            self.assertAlmostEqual(delay, bus.SCROLL_SPEED)

    def test_slow_steady_pacing_includes_render_time_and_resumes_after_pauses(self):
        self.observed_scroll(4, render_seconds=0.012)
        self.assertEqual(bus.SCROLL_SPEED, 0.05)
        # Check two downward runs and the return immediately after the bottom pause.
        for first, second in ((1, 2), (9, 10), (17, 18)):
            self.assertAlmostEqual(self.display_times[second][1] - self.display_times[first][1], 0.05)

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


class BusStartupTests(unittest.TestCase):
    def test_loading_frame_is_displayed_before_the_first_departure_fetch(self):
        class StopStartup(Exception):
            pass

        device = Mock()
        serial = ModuleType("luma.core.interface.serial")
        serial.spi = Mock()
        serial.noop = Mock()
        matrix = ModuleType("luma.led_matrix.device")
        matrix.max7219 = Mock(return_value=device)
        modules = {
            "luma.core.interface.serial": serial,
            "luma.led_matrix": ModuleType("luma.led_matrix"),
            "luma.led_matrix.device": matrix,
        }
        events = []
        device.display.side_effect = lambda _: events.append("loading")

        def fetch():
            self.assertEqual(events, ["loading"])
            events.append("fetch")
            raise StopStartup

        with patch.dict(sys.modules, modules), patch.object(bus, "device", None), \
                patch.object(bus, "get_departures", side_effect=fetch):
            with self.assertRaises(StopStartup):
                bus.main()
        self.assertEqual(events, ["loading", "fetch"])
        device.display.assert_called_once()
        image = device.display.call_args.args[0]
        self.assertEqual((image.mode, image.size), ("1", (128, 8)))
        self.assertIsNotNone(image.crop((0, 0, 64, 8)).getbbox())
        self.assertIsNotNone(image.crop((64, 0, 128, 8)).getbbox())


if __name__ == "__main__":
    unittest.main()
