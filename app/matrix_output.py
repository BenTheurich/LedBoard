"""Pack frames for this board's fixed 16-module MAX7219 chain."""

from PIL import Image


_REVERSE_BITS = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
_COMMANDS = bytes(value for digit in range(1, 9) for _ in range(16) for value in (digit, 0))


class MatrixOutput:
    def __init__(self, device):
        if (
            device.mode != "1"
            or device.size != (128, 8)
            or (device._w, device._h) != (128, 8)
            or device.cascaded != 16
            or device._correction_angle != -90
            or getattr(device, "rotate", 0) != 0
            or device.blocks_arranged_in_reverse_order
        ):
            raise ValueError("Matrix output requires this board's 128x8, 16-block, -90 degree configuration")
        self._device = device

    def display(self, image):
        if image.mode != "1" or image.size != (128, 8):
            raise ValueError("Matrix output needs a monochrome 128x8 physical frame")

        # For -90 degree modules, Luma's per-block rotation and vertical pixel
        # scan become a row flip, bit reversal and reversal of the 16 blocks.
        rows = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes().translate(_REVERSE_BITS)
        payload = bytearray(_COMMANDS)
        for digit in range(8):
            start, end = digit * 32, (digit + 1) * 32
            payload[start + 1:end:2] = rows[digit * 16:(digit + 1) * 16][::-1]
            self._device.data(payload[start:end])

    def contrast(self, value):
        return self._device.contrast(value)

    def show(self):
        return self._device.show()

    def close(self):
        return self._device.cleanup()


def create_matrix_output():
    """Open hardware only when the display owner requests it."""
    from luma.core.interface.serial import noop, spi
    from luma.led_matrix.device import max7219

    device = max7219(spi(port=0, device=0, gpio=noop()), cascaded=16,
                     block_orientation=-90, rotate=0)
    return MatrixOutput(device)
