from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from acid_rain import AcidRain
import effect_runner
from falling_sand import FallingSand
from harmonograph import Harmonograph


class EffectRunnerTests(unittest.TestCase):
    def test_all_three_effects_render_and_clear_through_the_shared_runner(self):
        for factory in (FallingSand, Harmonograph, AcidRain):
            with self.subTest(effect=factory.__name__):
                device = Mock()
                serial = ModuleType("luma.core.interface.serial")
                serial.spi = Mock()
                serial.noop = Mock()
                matrix = ModuleType("luma.led_matrix.device")
                matrix.max7219 = Mock(return_value=device)
                modules = {"luma.core.interface.serial": serial, "luma.led_matrix": ModuleType("luma.led_matrix"), "luma.led_matrix.device": matrix}
                with patch.dict(sys.modules, modules), patch.object(effect_runner.signal, "signal"), patch.object(effect_runner, "FramePacer") as pacer, redirect_stdout(io.StringIO()):
                    pacer.return_value.wait.side_effect = StopIteration
                    with self.assertRaises(StopIteration):
                        effect_runner.run(factory())
                device.display.assert_called_once()
                physical = device.display.call_args.args[0]
                self.assertEqual((physical.mode, physical.size), ("1", (128, 8)))
                device.clear.assert_called_once_with()
