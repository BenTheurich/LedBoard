from contextlib import contextmanager
import importlib.abc
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import mode_launcher
from frame_transport import FIRST, FRAME_BYTES, FrameProducer, decode_frames


class RejectHardwareImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("spidev", "RPi", "lgpio", "smbus", "luma.led_matrix",
                                "luma.core.interface.serial")):
            raise AssertionError(f"Worker tried to load hardware module {fullname}")


@contextmanager
def virtual_modules(producer):
    import luma
    import luma.core.interface

    with patch.dict(sys.modules), patch.object(luma, "led_matrix", None, create=True), \
            patch.object(luma.core.interface, "serial", None, create=True), \
            patch.object(sys, "meta_path", [RejectHardwareImports(), *sys.meta_path]):
        for name in list(sys.modules):
            if name.startswith(("luma.led_matrix", "luma.core.interface.serial")):
                del sys.modules[name]
        mode_launcher.install_frame_producer(producer)
        yield


class LauncherTests(unittest.TestCase):
    def test_virtual_hardware_imports_and_real_canvas_send_physical_pixels(self):
        frame_read, frame_write = os.pipe()
        resume_read, resume_write = os.pipe()
        producer = FrameProducer(frame_write, resume_read)
        try:
            os.write(resume_write, b"G")
            with virtual_modules(producer):
                from luma.core.interface.serial import noop, spi
                from luma.led_matrix.device import max7219
                from luma.core.render import canvas

                serial = spi(port=0, device=0, gpio=noop())
                device = max7219(serial, cascaded=16, rotate=0, block_orientation=-90)
                self.assertIs(device, producer)
                self.assertEqual((device.mode, device.size, device.width, device.height, device.rotate),
                                 ("1", (128, 8), 128, 8, 0))
                self.assertEqual(device.bounding_box, (0, 0, 127, 7))
                device.contrast(32)
                with canvas(device) as draw:
                    draw.rectangle(device.bounding_box, fill="black")
                    draw.point((0, 0), fill="white")
                    draw.point((127, 7), fill="white")
                kind, contrast, image = decode_frames(bytearray(os.read(frame_read, FRAME_BYTES)))[0]
                self.assertEqual((kind, contrast), (FIRST, 32))
                self.assertEqual(image.getpixel((0, 0)), 255)
                self.assertEqual(image.getpixel((127, 7)), 255)
                self.assertEqual(sum(bool(pixel) for pixel in image.getdata()), 2)
                serial.cleanup()
        finally:
            producer.cleanup()
            os.close(frame_read)
            os.close(resume_write)

    def test_virtual_matrix_rejects_other_physical_configurations(self):
        producer = Mock()
        with virtual_modules(producer):
            from luma.led_matrix.device import max7219

            expected = {"cascaded": 16, "rotate": 0, "block_orientation": -90}
            for change in ({"cascaded": 8}, {"rotate": 1}, {"block_orientation": 90},
                           {"width": 16}, {"blocks_arranged_in_reverse_order": True}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    max7219(None, **(expected | change))

    def test_adapter_is_installed_before_running_script_and_preserves_arguments(self):
        for filename in ("message.py", "drawing.py"):
            with self.subTest(filename=filename):
                producer = Mock()
                events = []

                def install(device):
                    self.assertIs(device, producer)
                    events.append("installed")

                def run(path, run_name):
                    self.assertEqual(events, ["installed"])
                    self.assertEqual((path, run_name), (filename, "__main__"))
                    self.assertEqual(sys.argv, [filename, "--message=--literal"])

                with patch.object(mode_launcher, "FrameProducer", return_value=producer) as create, \
                        patch.object(mode_launcher, "install_frame_producer", side_effect=install), \
                        patch.object(mode_launcher.runpy, "run_path", side_effect=run), \
                        patch.object(sys, "argv", ["mode_launcher.py"]):
                    result = mode_launcher.main(["--frame-fd", "11", "--resume-fd", "12",
                                                 "--", filename, "--message=--literal"])
                self.assertEqual(result, 0)
                create.assert_called_once_with(11, 12, allow_blank_first=filename == "drawing.py")
                producer.cleanup.assert_called_once_with()

    def test_script_failure_closes_transport_descriptors(self):
        producer = Mock()
        with patch.object(mode_launcher, "FrameProducer", return_value=producer), \
                patch.object(mode_launcher, "install_frame_producer"), \
                patch.object(mode_launcher.runpy, "run_path", side_effect=RuntimeError("mode failed")), \
                patch.object(sys, "argv", ["mode_launcher.py"]), self.assertRaisesRegex(RuntimeError, "mode failed"):
            mode_launcher.main(["--frame-fd", "11", "--resume-fd", "12", "--", "clock.py"])
        producer.cleanup.assert_called_once_with()

    def test_launcher_rejects_path_traversal_and_non_scripts_before_adapter_install(self):
        for filename in ("../clock.py", "sub/clock.py", r"sub\clock.py", "/tmp/clock.py", "clock.txt"):
            with self.subTest(filename=filename), patch.object(mode_launcher, "FrameProducer") as create, \
                    patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
                mode_launcher.main(["--frame-fd", "11", "--resume-fd", "12", "--", filename])
            self.assertEqual(error.exception.code, 2)
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
