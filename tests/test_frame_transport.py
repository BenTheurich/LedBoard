import os
from pathlib import Path
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from frame_transport import FIRST, FRAME, FRAME_BYTES, FrameProducer, decode_frames


class DecodingTests(unittest.TestCase):
    def test_partial_packets_remain_buffered_and_multiple_frames_preserve_pixels(self):
        pixels = bytes(range(128))
        first = struct.pack("!BB128s", FIRST, 255, pixels)
        second = struct.pack("!BB128s", FRAME, 0, bytes(128))
        self.assertEqual(FRAME_BYTES, 130)
        buffer = bytearray(first[:129])
        self.assertEqual(decode_frames(buffer), [])
        self.assertEqual(buffer, first[:129])
        buffer.extend(first[129:] + second + first[:17])
        frames = decode_frames(buffer)
        self.assertEqual([(kind, contrast) for kind, contrast, _ in frames], [(FIRST, 255), (FRAME, 0)])
        self.assertEqual(frames[0][2].mode, "1")
        self.assertEqual(frames[0][2].size, (128, 8))
        self.assertEqual(frames[0][2].tobytes(), pixels)
        self.assertIsNone(frames[1][2].getbbox())
        self.assertEqual(buffer, first[:17])

    def test_unknown_packet_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "packet kind"):
            decode_frames(bytearray(struct.pack("!BB128s", 3, 16, bytes(128))))


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.frame_read, self.frame_write = os.pipe()
        self.resume_read, self.resume_write = os.pipe()
        os.set_blocking(self.frame_read, False)
        self.producer = FrameProducer(self.frame_write, self.resume_read)
        self.image = Image.new("1", (128, 8))
        self.image.putpixel((127, 7), 1)

    def tearDown(self):
        self.producer.cleanup()
        for descriptor in (self.frame_read, self.resume_write):
            try:
                os.close(descriptor)
            except OSError:
                pass

    def read_frame(self):
        buffer = bytearray()
        deadline = time.monotonic() + 2
        while len(buffer) < FRAME_BYTES:
            try:
                data = os.read(self.frame_read, FRAME_BYTES - len(buffer))
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self.fail("Timed out waiting for a frame")
                time.sleep(.001)
                continue
            self.assertTrue(data, "Producer closed before a complete frame")
            buffer.extend(data)
        return decode_frames(buffer)[0]

    def assert_no_frame(self):
        with self.assertRaises(BlockingIOError):
            os.read(self.frame_read, FRAME_BYTES)

    def test_initial_blank_frames_are_ignored_then_first_waits_for_resume(self):
        self.producer.clear()
        self.producer.display(Image.new("1", (128, 8)))
        self.assert_no_frame()
        done = threading.Event()
        errors = []

        def render():
            try:
                self.producer.display(self.image)
            except BaseException as error:
                errors.append(error)
            finally:
                done.set()

        worker = threading.Thread(target=render, daemon=True)
        worker.start()
        try:
            kind, contrast, image = self.read_frame()
            self.assertEqual((kind, contrast), (FIRST, 16))
            self.assertEqual(image.tobytes(), self.image.tobytes())
            self.assertFalse(done.wait(.05), "First display returned before resume")
            os.write(self.resume_write, b"G")
            self.assertTrue(done.wait(1), "Producer did not resume")
            self.assertEqual(errors, [])
        finally:
            if not done.is_set():
                os.close(self.resume_write)
            worker.join(1)

    def test_empty_drawing_can_be_the_first_frame(self):
        self.producer = FrameProducer(self.frame_write, self.resume_read, allow_blank_first=True)
        os.write(self.resume_write, b"G")
        self.producer.clear()
        kind, _, image = self.read_frame()
        self.assertEqual(kind, FIRST)
        self.assertIsNone(image.getbbox())

    def test_loading_placeholder_does_not_send_or_wait_before_content_is_ready(self):
        # The producer has no resume signal, so sending FIRST here would block.
        with patch("frame_transport.os.read", side_effect=AssertionError("Loading waited for resume")):
            self.producer.display_loading(self.image)
        self.assert_no_frame()
        os.write(self.resume_write, b"G")
        actual = self.image.copy()
        actual.putpixel((0, 0), 1)
        self.producer.display(actual)
        kind, _, image = self.read_frame()
        self.assertEqual(kind, FIRST)
        self.assertEqual(image.tobytes(), actual.tobytes())

    def test_frames_deduplicate_pixels_and_contrast_but_send_brightness_changes(self):
        os.write(self.resume_write, b"G")
        self.producer.contrast(32)
        self.producer.display(self.image)
        self.assertEqual(self.read_frame()[:2], (FIRST, 32))
        self.producer.display(self.image.copy())
        self.producer.contrast(32)
        self.assert_no_frame()
        self.producer.contrast(64)
        kind, contrast, image = self.read_frame()
        self.assertEqual((kind, contrast), (FRAME, 64))
        self.assertEqual(image.tobytes(), self.image.tobytes())
        self.producer.clear()
        self.assertIsNone(self.read_frame()[2].getbbox())
        self.producer.clear()
        self.assert_no_frame()

    def test_hide_and_show_restore_the_latest_image(self):
        os.write(self.resume_write, b"G")
        self.producer.display(self.image)
        self.read_frame()
        self.producer.hide()
        self.assertIsNone(self.read_frame()[2].getbbox())
        self.producer.show()
        self.assertEqual(self.read_frame()[2].tobytes(), self.image.tobytes())

    def test_eof_or_invalid_resume_exits_cleanly_after_first_packet(self):
        for signal in (b"", b"X"):
            with self.subTest(signal=signal):
                frame_read, frame_write = os.pipe()
                resume_read, resume_write = os.pipe()
                producer = FrameProducer(frame_write, resume_read)
                try:
                    if signal:
                        os.write(resume_write, signal)
                    os.close(resume_write)
                    with self.assertRaises(SystemExit) as error:
                        producer.display(self.image)
                    self.assertEqual(error.exception.code, 0)
                    self.assertEqual(decode_frames(bytearray(os.read(frame_read, FRAME_BYTES)))[0][0], FIRST)
                finally:
                    producer.cleanup()
                    os.close(frame_read)

    def test_partial_writes_and_interrupted_io_preserve_the_packet(self):
        os.write(self.resume_write, b"G")
        real_write, real_read = os.write, os.read
        write_calls, read_calls = [], []

        def write(descriptor, data):
            write_calls.append(len(data))
            if len(write_calls) == 1:
                raise InterruptedError
            return real_write(descriptor, data[:17])

        def read(descriptor, count):
            read_calls.append(count)
            if len(read_calls) == 1:
                raise InterruptedError
            return real_read(descriptor, count)

        with patch("frame_transport.os.write", side_effect=write), patch("frame_transport.os.read", side_effect=read):
            self.producer.display(self.image)
        self.assertGreater(len(write_calls), 2)
        self.assertEqual(len(read_calls), 2)
        self.assertEqual(self.read_frame()[2].tobytes(), self.image.tobytes())

    def test_broken_frame_pipe_exits_cleanly_and_cleanup_is_idempotent(self):
        os.close(self.frame_read)
        with self.assertRaises(SystemExit) as error:
            self.producer.display(self.image)
        self.assertEqual(error.exception.code, 0)
        self.producer.cleanup()
        self.producer.cleanup()
        with self.assertRaises(OSError):
            os.fstat(self.producer._frame_fd)

    def test_invalid_geometry_or_contrast_is_rejected_before_writing(self):
        for image in (Image.new("RGB", (128, 8)), Image.new("1", (64, 16))):
            with self.subTest(image=image), self.assertRaises(ValueError):
                self.producer.display(image)
            with self.subTest(loading=image), self.assertRaises(ValueError):
                self.producer.display_loading(image)
        for value in (-1, 256, 1.5, "16"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.producer.contrast(value)
        self.assert_no_frame()


if __name__ == "__main__":
    unittest.main()
