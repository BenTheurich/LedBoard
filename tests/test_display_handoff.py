from pathlib import Path
import json
import os
import select
import signal
import subprocess
import sys
import textwrap
import time
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import display_handoff
from display_utils import map_serpentine


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def tick(self):
        self.now += 0.025


class WipeTests(unittest.TestCase):
    def test_wipe_erases_or_reveals_the_same_logical_columns_in_both_rows(self):
        logical = Image.new("1", (64, 16), 1)
        original = map_serpentine(logical)
        erased = display_handoff.wipe_frame(original, 0.5)
        revealed = display_handoff.wipe_frame(original, 0.5, reveal=True)
        for y in range(16):
            for x in range(64):
                physical = (x, y) if y < 8 else (127 - x, 15 - y)
                self.assertEqual(bool(erased.getpixel(physical)), x >= 32)
                self.assertEqual(bool(revealed.getpixel(physical)), x < 32)

    def test_wipes_preserve_only_target_pixels_and_have_exact_endpoints(self):
        logical = Image.new("1", (64, 16), 0)
        for point in ((0, 0), (63, 0), (0, 15), (63, 15), (20, 8), (42, 7)):
            logical.putpixel(point, 1)
        original = map_serpentine(logical)
        original_pixels = set(index for index, on in enumerate(original.getdata()) if on)
        for reveal in (False, True):
            previous = set() if reveal else original_pixels
            for progress in (0, .1, .3, .5, .8, 1):
                frame = display_handoff.wipe_frame(original, progress, reveal=reveal)
                pixels = set(index for index, on in enumerate(frame.getdata()) if on)
                self.assertLessEqual(pixels, original_pixels)
                self.assertLessEqual(previous, pixels) if reveal else self.assertLessEqual(pixels, previous)
                previous = pixels
            self.assertEqual(previous, original_pixels if reveal else set())
        self.assertEqual(display_handoff.wipe_frame(original, 0).tobytes(), original.tobytes())
        self.assertIsNone(display_handoff.wipe_frame(original, 0, reveal=True).getbbox())
        self.assertIsNone(display_handoff.wipe_frame(original, 1).getbbox())
        self.assertEqual(display_handoff.wipe_frame(original, 1, reveal=True).tobytes(), original.tobytes())


class HandoffTests(unittest.TestCase):
    def setUp(self):
        class Matrix:
            def __init__(self):
                self.frames = []
                self.persist = False
                self.display(Image.new("1", (128, 8), 0))

            def display(self, image):
                self.frames.append(image.copy())

            def clear(self):
                self.display(Image.new("1", (128, 8), 0))

        self.Matrix = Matrix
        module = ModuleType("luma.led_matrix.device")
        module.max7219 = Matrix
        self.modules = {"luma.led_matrix": ModuleType("luma.led_matrix"), "luma.led_matrix.device": module}
        self.clock = FakeClock()
        self.signal_handlers = {}
        self.patches = [
            patch.dict(sys.modules, self.modules),
            patch.object(display_handoff.time, "monotonic", side_effect=lambda: self.clock.now),
            patch.object(display_handoff, "FramePacer"),
            patch.object(display_handoff.signal, "signal", side_effect=lambda number, handler: self.signal_handlers.update({number: handler})),
            patch.object(display_handoff, "_atomic_frame"),
        ]
        self.started = [item.start() for item in self.patches]
        self.started[2].return_value.wait.side_effect = self.clock.tick
        self.started[4].return_value.__enter__.return_value = None
        display_handoff.install_handoff()
        self.device = Matrix()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_constructor_and_blank_flush_do_not_consume_first_reveal(self):
        self.assertTrue(self.device.persist)
        self.assertEqual(len(self.device.frames), 1)
        self.device.clear()
        target = Image.new("1", (128, 8), 1)
        before = len(self.device.frames)
        self.device.display(target)
        reveal = self.device.frames[before:]
        self.assertGreater(len(reveal), 2)
        self.assertIsNone(reveal[0].getbbox())
        self.assertEqual(reveal[-1].tobytes(), target.tobytes())
        self.assertGreaterEqual(self.clock.now, display_handoff.SWEEP_SECONDS)
        target.putpixel((5, 5), 0)
        before = len(self.device.frames)
        self.device.display(target)
        self.assertEqual(len(self.device.frames), before + 1)

    def test_term_erases_latest_successful_frame_and_later_cleanup_cannot_write(self):
        target = Image.new("1", (128, 8), 0)
        target.putpixel((12, 3), 1)
        target.putpixel((115, 4), 1)
        self.device.display(target)
        latest = Image.new("1", (128, 8), 1)
        self.device.display(latest)
        before = len(self.device.frames)
        handler = self.signal_handlers[display_handoff.signal.SIGTERM]
        with self.assertRaises(SystemExit) as stopped:
            handler(None, None)
        self.assertEqual(stopped.exception.code, 0)
        erased = self.device.frames[before:]
        self.assertEqual(erased[0].tobytes(), latest.tobytes())
        self.assertIsNone(erased[-1].getbbox())
        before = len(self.device.frames)
        self.device.clear()
        self.device.display(latest)
        self.assertEqual(len(self.device.frames), before)

    def test_snapshot_is_a_copy_and_failed_writes_do_not_replace_it(self):
        target = Image.new("1", (128, 8), 1)
        self.device.display(target)
        state = self.device._garching_handoff
        saved = state.last_frame.tobytes()
        target.paste(0, (0, 0, 128, 8))
        self.assertEqual(state.last_frame.tobytes(), saved)
        with patch.object(state, "original_display", side_effect=OSError("SPI failed")):
            with self.assertRaises(OSError):
                self.device.display(target)
        self.assertEqual(state.last_frame.tobytes(), saved)

    def test_frame_write_and_snapshot_finish_before_sigterm_is_unblocked(self):
        self.patches[4].stop()
        target = Image.new("1", (128, 8), 1)
        state = self.device._garching_handoff
        state.revealed = True
        events = []

        def mask(operation, values):
            if operation == "restore":
                self.assertEqual(state.last_frame.tobytes(), target.tobytes())
            events.append(operation)
            return set()

        original = state.original_display
        with patch.object(display_handoff.signal, "pthread_sigmask", side_effect=mask, create=True), \
                patch.object(display_handoff.signal, "SIG_BLOCK", "block", create=True), \
                patch.object(display_handoff.signal, "SIG_SETMASK", "restore", create=True), \
                patch.object(state, "original_display", side_effect=lambda device, frame: (events.append("write"), original(device, frame))):
            self.device.display(target)
        self.assertEqual(events, ["block", "write", "restore"])

    def test_term_received_during_write_waits_for_the_successful_snapshot(self):
        state = self.device._garching_handoff
        state.revealed = True
        target = Image.new("1", (128, 8), 1)
        original = state.original_display
        before = len(self.device.frames)

        def interrupted_write(device, image):
            original(device, image)
            if not state.stopping:
                state.stop(None, None)
                self.assertTrue(state.pending_stop)
                self.assertFalse(state.stopping)

        with patch.object(state, "original_display", side_effect=interrupted_write):
            with self.assertRaises(SystemExit):
                self.device.display(target)
        frames = self.device.frames[before:]
        self.assertEqual(frames[0].tobytes(), target.tobytes())
        self.assertEqual(frames[1].tobytes(), target.tobytes())
        self.assertIsNone(frames[-1].getbbox())


class AtomicFrameTests(unittest.TestCase):
    def test_sigterm_is_blocked_until_the_snapshot_has_been_recorded(self):
        events = []
        old_mask = {"previous-mask"}

        def mask(operation, values):
            events.append((operation, values))
            return old_mask

        with patch.object(display_handoff.signal, "pthread_sigmask", side_effect=mask, create=True), \
                patch.object(display_handoff.signal, "SIG_BLOCK", "block", create=True), \
                patch.object(display_handoff.signal, "SIG_SETMASK", "restore", create=True):
            with display_handoff._atomic_frame():
                events.append("write-and-snapshot")
        self.assertEqual(events, [("block", {display_handoff.signal.SIGTERM}), "write-and-snapshot", ("restore", old_mask)])

    @unittest.skipUnless(os.name == "posix" and hasattr(signal, "pthread_sigmask"), "POSIX signal masks required")
    def test_real_term_during_reveal_finishes_then_erases_without_cleanup_redraw(self):
        code = textwrap.dedent('''
            import json, signal, sys, threading
            from types import ModuleType
            from PIL import Image
            sys.path.insert(0, sys.argv[1])
            import display_handoff

            class Matrix:
                def __init__(self):
                    self.frames = []
                    self.announced = False
                    self.display(Image.new('1', (128, 8), 0))
                def display(self, image):
                    state = self._garching_handoff
                    phase = 'init' if state.initializing else 'erase' if state.stopping else 'reveal'
                    self.frames.append((phase, sum(bool(pixel) for pixel in image.getdata())))
                    if phase == 'reveal' and not self.announced:
                        self.announced = True
                        print('REVEAL_STARTED', flush=True)
                        # TERM is sent before this acknowledgement, guaranteeing
                        # it is pending inside the real blocked frame section.
                        assert sys.stdin.buffer.read(1) == b'G'
                def clear(self):
                    self.display(Image.new('1', (128, 8), 0))

            module = ModuleType('luma.led_matrix.device')
            module.max7219 = Matrix
            sys.modules['luma.led_matrix'] = ModuleType('luma.led_matrix')
            sys.modules['luma.led_matrix.device'] = module
            display_handoff.install_handoff()
            device = Matrix()
            state = device._garching_handoff
            observed = {'deferred': False}
            def stopping(*args):
                observed['deferred'] = bool(state.frame_depth)
                return state.stop(*args)
            signal.signal(signal.SIGTERM, stopping)
            background_ready = threading.Event()
            def background():
                signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})
                background_ready.set()
                threading.Event().wait()
            threading.Thread(target=background, daemon=True).start()
            assert background_ready.wait(2)
            try:
                device.display(Image.new('1', (128, 8), 1))
            except SystemExit as stopped:
                assert stopped.code == 0
            else:
                raise AssertionError('TERM did not interrupt the reveal')
            before = len(device.frames)
            device.clear()
            device.display(Image.new('1', (128, 8), 1))
            assert len(device.frames) == before
            report = {phase: [count for kind, count in device.frames if kind == phase]
                      for phase in ('reveal', 'erase')}
            report['deferred'] = observed['deferred']
            print(json.dumps(report), flush=True)
        ''')
        app_root = str(Path(__file__).resolve().parents[1] / "app")
        process = subprocess.Popen([sys.executable, "-B", "-c", code, app_root],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 15)[0], "Child did not begin reveal")
            self.assertEqual(process.stdout.readline(), b"REVEAL_STARTED\n")
            started = time.monotonic()
            os.kill(process.pid, signal.SIGTERM)
            process.stdin.write(b"G")
            process.stdin.flush()
            output, errors = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, errors.decode(errors="replace"))
            self.assertLess(time.monotonic() - started, 3)
            report = json.loads(output)
            self.assertTrue(report["deferred"])
            self.assertEqual((report["reveal"][0], report["reveal"][-1]), (0, 1024))
            self.assertEqual(report["reveal"], sorted(report["reveal"]))
            self.assertEqual((report["erase"][0], report["erase"][-1]), (1024, 0))
            self.assertEqual(report["erase"], sorted(report["erase"], reverse=True))
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
