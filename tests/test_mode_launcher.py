import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import mode_launcher


class LauncherTests(unittest.TestCase):
    def test_preparation_imports_modules_without_initializing_hardware(self):
        serial = ModuleType("luma.core.interface.serial")
        serial.spi, serial.noop = Mock(), Mock()
        matrix = ModuleType("luma.led_matrix.device")
        matrix.max7219 = Mock()
        render = ModuleType("luma.core.render")
        render.canvas = Mock()
        modules = {"clock": ModuleType("clock"), "luma.core.interface.serial": serial,
                   "luma.led_matrix": ModuleType("luma.led_matrix"),
                   "luma.led_matrix.device": matrix, "luma.core.render": render}
        with patch.dict(sys.modules, modules):
            mode_launcher.prepare_mode("clock.py")
        serial.spi.assert_not_called()
        matrix.max7219.assert_not_called()
        render.canvas.assert_not_called()

    def test_go_precedes_handoff_installation_and_script_execution(self):
        ready_read, ready_write = os.pipe()
        go_read, go_write = os.pipe()
        os.set_blocking(ready_read, False)
        os.write(go_write, b"G")
        events = []

        def prepare(filename):
            self.assertEqual(filename, "message.py")
            with self.assertRaises(BlockingIOError):
                os.read(ready_read, 1)
            events.append("prepared")

        def install():
            self.assertEqual(os.read(ready_read, 1), b"R")
            # The bootstrap has consumed GO and closed its handoff channel.
            with self.assertRaises(OSError):
                os.fstat(go_read)
            events.append("installed")

        def run(filename, run_name):
            self.assertEqual(events, ["prepared", "installed"])
            self.assertEqual((filename, run_name), ("message.py", "__main__"))
            self.assertEqual(sys.argv, ["message.py", "--message=--literal"])
            events.append("ran")

        try:
            with patch.object(mode_launcher, "prepare_mode", side_effect=prepare), \
                    patch.object(mode_launcher, "install_handoff", side_effect=install), \
                    patch.object(mode_launcher.runpy, "run_path", side_effect=run), \
                    patch.object(sys, "argv", ["mode_launcher.py"]):
                mode_launcher.main(["--ready-fd", str(ready_write), "--go-fd", str(go_read),
                                    "--", "message.py", "--message=--literal"])
            self.assertEqual(events, ["prepared", "installed", "ran"])
        finally:
            for descriptor in (ready_read, ready_write, go_read, go_write):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def test_eof_or_invalid_go_cannot_execute_a_mode(self):
        for signal in (b"", b"X"):
            with self.subTest(signal=signal):
                ready_read, ready_write = os.pipe()
                go_read, go_write = os.pipe()
                if signal:
                    os.write(go_write, signal)
                os.close(go_write)
                try:
                    with patch.object(mode_launcher, "prepare_mode"), \
                            patch.object(mode_launcher, "install_handoff") as install, \
                            patch.object(mode_launcher.runpy, "run_path") as run:
                        try:
                            mode_launcher.main(["--ready-fd", str(ready_write), "--go-fd", str(go_read),
                                                "--", "clock.py"])
                        except (SystemExit, RuntimeError, ValueError):
                            pass
                    run.assert_not_called()
                    install.assert_not_called()
                finally:
                    for descriptor in (ready_read, ready_write, go_read):
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass


if __name__ == "__main__":
    unittest.main()
