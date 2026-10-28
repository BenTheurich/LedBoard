from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))
import game_of_life as life


class StopSimulation(Exception):
    pass


class GameOfLifeStartupTests(unittest.TestCase):
    def hardware_modules(self, device):
        serial = ModuleType("luma.core.interface.serial")
        serial.spi = Mock()
        serial.noop = Mock()
        matrix = ModuleType("luma.led_matrix.device")
        matrix.max7219 = Mock(return_value=device)
        render = ModuleType("luma.core.render")
        render.canvas = Mock()
        return serial, matrix, render, {
            "luma.core.interface.serial": serial,
            "luma.led_matrix": ModuleType("luma.led_matrix"),
            "luma.led_matrix.device": matrix,
            "luma.core.render": render,
        }

    def test_import_does_not_initialize_hardware_or_wait(self):
        serial, matrix, render, modules = self.hardware_modules(Mock())
        spec = importlib.util.spec_from_file_location("life_import_probe", APP_ROOT / "game_of_life.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules), patch.object(life.time, "sleep") as sleep:
            spec.loader.exec_module(module)
        serial.spi.assert_not_called()
        matrix.max7219.assert_not_called()
        render.canvas.assert_not_called()
        sleep.assert_not_called()
        self.assertTrue(callable(module.main))

    def test_main_draws_first_generation_before_the_normal_frame_wait(self):
        device = Mock(bounding_box=(0, 0, 127, 7))
        _, _, render, modules = self.hardware_modules(device)
        draw = Mock()
        events = []

        @contextmanager
        def canvas(_):
            yield draw

        render.canvas = canvas
        game = Mock()
        game.draw.side_effect = lambda _: events.append("frame")
        game.step.return_value = (1, 1)
        game.is_stuck_in_loop.return_value = False

        def wait(_):
            events.append("wait")
            raise StopSimulation

        with patch.dict(sys.modules, modules), patch.object(life, "GameOfLife", return_value=game), \
                patch.object(life.time, "sleep", side_effect=wait) as sleep:
            with self.assertRaises(StopSimulation):
                life.main()
        self.assertEqual(events, ["frame", "wait"])
        sleep.assert_called_once_with(life.SPEED)
        draw.rectangle.assert_called_once_with(device.bounding_box, fill="black")
        game.reset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
