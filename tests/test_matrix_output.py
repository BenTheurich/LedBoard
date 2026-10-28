import random
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from matrix_output import MatrixOutput, create_matrix_output


def legacy_packets(image):
    """Independently reproduce Luma's block rotations and column bit scan."""
    rotated = image.copy()
    for x in range(0, 128, 8):
        box = (x, 0, x + 8, 8)
        rotated.paste(image.crop(box).rotate(-90), box)
    pixels = list(rotated.getdata())
    packets = []
    for digit in range(8):
        packet = []
        for offset in range(120, -8, -8):
            byte = 0
            for y in range(8):
                if pixels[offset + digit + y * 128] > 0:
                    byte |= 1 << y
            packet.extend((digit + 1, byte))
        packets.append(bytes(packet))
    return packets


class RecordingDevice:
    mode = "1"
    size = (128, 8)
    _w, _h = 128, 8
    cascaded = 16
    _correction_angle = -90
    rotate = 0
    blocks_arranged_in_reverse_order = False

    def __init__(self):
        self.packets = []
        self.contrast = Mock()
        self.show = Mock()
        self.cleanup = Mock()

    def data(self, packet):
        self.packets.append(bytes(packet))


class MatrixOutputTests(unittest.TestCase):
    def test_packets_match_legacy_for_every_single_pixel(self):
        device = RecordingDevice()
        output = MatrixOutput(device)
        for y in range(8):
            for x in range(128):
                with self.subTest(x=x, y=y):
                    image = Image.new("1", (128, 8))
                    image.putpixel((x, y), 1)
                    device.packets.clear()
                    output.display(image)
                    self.assertEqual(device.packets, legacy_packets(image))

    def test_packets_match_legacy_for_blank_full_and_random_frames(self):
        rng = random.Random(7219)
        frames = [Image.new("1", (128, 8), value) for value in (0, 1)]
        frames.extend(Image.frombytes("1", (128, 8), bytes(rng.getrandbits(8) for _ in range(128)))
                      for _ in range(32))
        device = RecordingDevice()
        output = MatrixOutput(device)
        for index, image in enumerate(frames):
            with self.subTest(index=index):
                device.packets.clear()
                output.display(image)
                self.assertEqual(device.packets, legacy_packets(image))
                self.assertEqual(len(device.packets), 8)
                self.assertTrue(all(len(packet) == 32 for packet in device.packets))

    def test_rejects_unsupported_device_configuration(self):
        for name, value in (
            ("mode", "RGB"), ("size", (64, 16)), ("_w", 64), ("_h", 16),
            ("cascaded", 8), ("_correction_angle", 90), ("rotate", 2),
            ("blocks_arranged_in_reverse_order", True),
        ):
            with self.subTest(name=name):
                device = RecordingDevice()
                setattr(device, name, value)
                with self.assertRaises(ValueError):
                    MatrixOutput(device)
                self.assertEqual(device.packets, [])

    def test_rejects_wrong_image_before_writing(self):
        device = RecordingDevice()
        output = MatrixOutput(device)
        for mode, size in (("RGB", (128, 8)), ("1", (64, 16)), ("1", (128, 16))):
            with self.subTest(mode=mode, size=size):
                with self.assertRaises(ValueError):
                    output.display(Image.new(mode, size))
        self.assertEqual(device.packets, [])

    def test_controls_and_close_delegate_to_device(self):
        device = RecordingDevice()
        output = MatrixOutput(device)
        output.contrast(16)
        output.show()
        output.close()
        device.contrast.assert_called_once_with(16)
        device.show.assert_called_once_with()
        device.cleanup.assert_called_once_with()

    def test_factory_opens_fixed_board_configuration_lazily(self):
        device = RecordingDevice()
        serial = ModuleType("luma.core.interface.serial")
        serial.spi, serial.noop = Mock(), Mock()
        matrix = ModuleType("luma.led_matrix.device")
        matrix.max7219 = Mock(return_value=device)
        modules = {"luma.core.interface.serial": serial,
                   "luma.led_matrix": ModuleType("luma.led_matrix"),
                   "luma.led_matrix.device": matrix}
        with patch.dict(sys.modules, modules):
            output = create_matrix_output()
        self.assertIsInstance(output, MatrixOutput)
        serial.noop.assert_called_once_with()
        serial.spi.assert_called_once_with(port=0, device=0, gpio=serial.noop.return_value)
        matrix.max7219.assert_called_once_with(serial.spi.return_value, cascaded=16,
                                               block_orientation=-90, rotate=0)


if __name__ == "__main__":
    unittest.main()
