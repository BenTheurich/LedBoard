from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from acid_rain import AcidRain
import effect_runner
from falling_sand import FallingSand
from harmonograph import Harmonograph


class EffectRunnerTests(unittest.TestCase):
    def run_frames(self, effect, device, count=1):
        serial = ModuleType("luma.core.interface.serial")
        serial.spi, serial.noop = Mock(), Mock()
        matrix = ModuleType("luma.led_matrix.device")
        matrix.max7219 = Mock(return_value=device)
        modules = {"luma.core.interface.serial": serial,
                   "luma.led_matrix": ModuleType("luma.led_matrix"),
                   "luma.led_matrix.device": matrix}
        with patch.dict(sys.modules, modules), patch.object(effect_runner.signal, "signal"), \
                patch.object(effect_runner, "FramePacer") as pacer, redirect_stdout(io.StringIO()):
            pacer.return_value.wait.side_effect = [None] * (count - 1) + [StopIteration]
            with self.assertRaises(StopIteration):
                effect_runner.run(effect)

    def test_all_three_effects_render_and_clear_through_the_shared_runner(self):
        for factory in (FallingSand, Harmonograph, AcidRain):
            with self.subTest(effect=factory.__name__):
                device = Mock(spec=["display", "contrast", "clear"])
                self.run_frames(factory(), device)
                device.display.assert_called_once()
                physical = device.display.call_args.args[0]
                self.assertEqual((physical.mode, physical.size), ("1", (128, 8)))
                device.clear.assert_called_once_with()

    def test_readiness_is_sampled_before_rendering_to_avoid_revealing_a_placeholder(self):
        class PreparingEffect:
            ready = False

            def render(self, elapsed, delta):
                image = Image.new("1", (64, 16))
                image.putpixel((1 if self.ready else 0, 0), 1)
                self.ready = True
                return image

        device = Mock(spec=["display", "display_loading", "contrast", "clear"])
        self.run_frames(PreparingEffect(), device, count=2)
        device.display_loading.assert_called_once()
        device.display.assert_called_once()
        self.assertTrue(device.display_loading.call_args.args[0].getpixel((0, 0)))
        self.assertTrue(device.display.call_args.args[0].getpixel((1, 0)))

    def test_standalone_device_still_displays_loading(self):
        class PreparingEffect:
            ready = False

            def render(self, elapsed, delta):
                return Image.new("1", (64, 16), 1)

        device = Mock(spec=["display", "contrast", "clear"])
        self.run_frames(PreparingEffect(), device)
        device.display.assert_called_once()
        self.assertIsNotNone(device.display.call_args.args[0].getbbox())
