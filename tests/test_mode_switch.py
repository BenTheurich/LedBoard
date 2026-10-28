import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import mode_switch


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def tick(self):
        self.now += 1 / mode_switch.TRANSITION_FPS


class TransitionTests(unittest.TestCase):
    def test_controller_reuses_its_matrix_handle(self):
        device = Mock()
        serial = ModuleType("luma.core.interface.serial")
        serial.spi, serial.noop = Mock(), Mock()
        matrix = ModuleType("luma.led_matrix.device")
        matrix.max7219 = Mock(return_value=device)
        modules = {"luma.core.interface.serial": serial,
                   "luma.led_matrix": ModuleType("luma.led_matrix"),
                   "luma.led_matrix.device": matrix}
        mode_switch.get_matrix_device.cache_clear()
        try:
            with patch.dict(sys.modules, modules):
                self.assertIs(mode_switch.get_matrix_device(), device)
                self.assertIs(mode_switch.get_matrix_device(), device)
            serial.spi.assert_called_once()
            matrix.max7219.assert_called_once()
        finally:
            mode_switch.get_matrix_device.cache_clear()

    def test_reset_frames_are_monochrome_full_panel_images_that_move(self):
        frames = [mode_switch.render_reset(elapsed) for elapsed in (0.1, 0.2, 0.3)]
        for frame in frames:
            self.assertEqual((frame.mode, frame.size), ("1", (64, 16)))
            self.assertIsNotNone(frame.getbbox())
        self.assertEqual(len({frame.tobytes() for frame in frames}), 3)

    def test_animation_covers_preparation_and_finishes_with_a_clear(self):
        clock = FakeClock()
        device = Mock()
        with patch.object(mode_switch, "get_matrix_device", return_value=device), \
                patch.object(mode_switch.time, "monotonic", side_effect=lambda: clock.now), \
                patch.object(mode_switch, "FramePacer") as pacer:
            pacer.return_value.wait.side_effect = clock.tick
            mode_switch.animate_reset(lambda: clock.now >= 0.28, duration=0.12, timeout=1)
        self.assertGreaterEqual(clock.now, mode_switch.SWEEP_SECONDS)
        self.assertLess(clock.now, mode_switch.SWEEP_SECONDS + 0.08)
        self.assertGreater(device.display.call_count, 1)
        methods = [entry[0] for entry in device.mock_calls]
        self.assertLess(methods.index("show"), methods.index("display"))
        device.show.assert_called_once_with()
        for arguments in device.display.call_args_list:
            image = arguments.args[0]
            self.assertEqual((image.mode, image.size), ("1", (128, 8)))
        device.clear.assert_called_once_with()
        pacer.assert_called_once_with(mode_switch.TRANSITION_FPS)

    def test_off_clear_does_not_restart_a_white_reset_sweep(self):
        device = Mock()
        with patch.object(mode_switch, "get_matrix_device", return_value=device):
            mode_switch.clear_display()
        device.clear.assert_called_once_with()
        device.display.assert_not_called()

    def test_reset_sweep_respects_its_minimum_duration_without_a_ready_callback(self):
        clock = FakeClock()
        device = Mock()
        with patch.object(mode_switch, "get_matrix_device", return_value=device), \
                patch.object(mode_switch.time, "monotonic", side_effect=lambda: clock.now), \
                patch.object(mode_switch, "FramePacer") as pacer:
            pacer.return_value.wait.side_effect = clock.tick
            mode_switch.animate_reset(duration=0.12)
        self.assertGreaterEqual(clock.now, 0.12)
        self.assertLess(clock.now, 0.2)
        device.clear.assert_called_once_with()

    def test_timeout_and_preparation_failure_clear_the_panel(self):
        for failure in ("timeout", "ready-error"):
            with self.subTest(failure=failure):
                clock = FakeClock()
                device = Mock()
                ready = Mock(return_value=False)
                if failure == "ready-error":
                    ready.side_effect = RuntimeError("Preparation failed")
                with patch.object(mode_switch, "get_matrix_device", return_value=device), \
                        patch.object(mode_switch.time, "monotonic", side_effect=lambda: clock.now), \
                        patch.object(mode_switch, "FramePacer") as pacer:
                    pacer.return_value.wait.side_effect = clock.tick
                    with self.assertRaises((TimeoutError, RuntimeError)):
                        mode_switch.animate_reset(ready, duration=0.04, timeout=0.12)
                device.clear.assert_called_once_with()


class LaunchTests(unittest.TestCase):
    def test_ready_go_handoff_keeps_worker_waiting_until_animation_has_stopped(self):
        process = Mock()
        process.poll.return_value = None
        go_reader = []
        captured = {}

        def spawn(arguments, **kwargs):
            captured.update(arguments=arguments, kwargs=kwargs)
            ready_fd = int(arguments[arguments.index("--ready-fd") + 1])
            go_fd = int(arguments[arguments.index("--go-fd") + 1])
            self.assertEqual(set(kwargs["pass_fds"]), {ready_fd, go_fd})
            go_reader.append(os.dup(go_fd))
            os.set_blocking(go_reader[0], False)
            os.write(ready_fd, b"R")
            return process

        def animate(ready):
            self.assertTrue(ready())
            with self.assertRaises(BlockingIOError):
                os.read(go_reader[0], 1)

        try:
            with patch.object(mode_switch.subprocess, "Popen", side_effect=spawn), \
                    patch.object(mode_switch, "animate_reset", side_effect=animate):
                result = mode_switch.launch_mode("message.py", ("--message=--hello; $(literal)",))
            self.assertIs(result, process)
            self.assertEqual(os.read(go_reader[0], 1), b"G")
            self.assertEqual(captured["arguments"][:2], ["python3", "mode_launcher.py"])
            self.assertEqual(captured["arguments"][-3:], ["--", "message.py", "--message=--hello; $(literal)"])
            self.assertNotEqual(captured["kwargs"].get("stdout"), subprocess.PIPE)
            self.assertNotEqual(captured["kwargs"].get("stderr"), subprocess.PIPE)
            process.terminate.assert_not_called()
        finally:
            for descriptor in go_reader:
                os.close(descriptor)

    def test_failed_preparation_never_releases_worker_and_reaps_it(self):
        for failure in ("eof", "timeout", "render"):
            with self.subTest(failure=failure):
                process = Mock()
                process.poll.return_value = None
                go_reader = []

                def spawn(arguments, **kwargs):
                    go_fd = int(arguments[arguments.index("--go-fd") + 1])
                    go_reader.append(os.dup(go_fd))
                    return process

                def animate(ready):
                    if failure == "eof":
                        ready()
                    elif failure == "timeout":
                        raise TimeoutError("No ready signal")
                    else:
                        raise OSError("SPI failed")

                try:
                    with patch.object(mode_switch.subprocess, "Popen", side_effect=spawn), \
                            patch.object(mode_switch, "animate_reset", side_effect=animate), \
                            patch.object(mode_switch, "get_matrix_device"):
                        with self.assertRaises(mode_switch.ModeStartError):
                            mode_switch.launch_mode("clock.py")
                    self.assertEqual(os.read(go_reader[0], 1), b"")
                    process.terminate.assert_called_once_with()
                    process.wait.assert_called_once_with(timeout=2)
                finally:
                    for descriptor in go_reader:
                        os.close(descriptor)

    def test_failed_spawn_closes_parent_pipe_descriptors(self):
        descriptors = []
        real_pipe = os.pipe

        def pipe():
            pair = real_pipe()
            descriptors.extend(pair)
            return pair

        with patch.object(mode_switch.os, "pipe", side_effect=pipe), \
                patch.object(mode_switch.subprocess, "Popen", side_effect=OSError("Cannot start process")), \
                patch.object(mode_switch, "animate_reset") as animate, \
                patch.object(mode_switch, "get_matrix_device") as matrix:
            with self.assertRaises(mode_switch.ModeStartError):
                mode_switch.launch_mode("clock.py")
        animate.assert_not_called()
        matrix.return_value.clear.assert_called_once_with()
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_stubborn_worker_is_killed_and_reaped(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("worker", 2), 0]
        mode_switch.stop_process(process)
        self.assertEqual(process.method_calls, [call.terminate(), call.wait(timeout=2), call.kill(), call.wait()])


if __name__ == "__main__":
    unittest.main()
