"""Carry physical matrix frames from a renderer to the sole display owner."""

import errno
import os
import struct

from PIL import Image


FRAME, FIRST = 1, 2
_PACKET = struct.Struct("!BB128s")
FRAME_BYTES = _PACKET.size
_BLANK = bytes(128)


def decode_frames(buffer: bytearray):
    """Consume whole packets, leaving an incomplete trailing packet buffered."""
    frames = []
    consumed = 0
    while len(buffer) - consumed >= FRAME_BYTES:
        kind, contrast, pixels = _PACKET.unpack_from(buffer, consumed)
        if kind not in (FRAME, FIRST):
            raise ValueError(f"Unknown frame packet kind: {kind}")
        frames.append((kind, contrast, Image.frombytes("1", (128, 8), pixels)))
        consumed += FRAME_BYTES
    del buffer[:consumed]
    return frames


class FrameProducer:
    """A small Luma-compatible device that never opens SPI or GPIO."""

    size, mode = (128, 8), "1"
    width, height = size
    bounding_box = (0, 0, width - 1, height - 1)
    rotate = 0

    def __init__(self, frame_fd, resume_fd, allow_blank_first=False):
        self._frame_fd = frame_fd
        self._resume_fd = resume_fd
        self._allow_blank_first = allow_blank_first
        self._contrast = 16
        self._started = False
        self._last_frame = None
        self._pixels = None
        self._hidden = False
        self._closed = False

    def _write(self, packet):
        # Each packet is below PIPE_BUF. Retry interruptions and short writes
        # without dropping bytes, even though ordinary pipe writes are atomic.
        remaining = memoryview(packet)
        while remaining:
            try:
                written = os.write(self._frame_fd, remaining)
            except InterruptedError:
                continue
            except OSError as error:
                # Windows anonymous pipes report a closed reader as EINVAL.
                if error.errno == errno.EPIPE or (os.name == "nt" and error.errno == errno.EINVAL):
                    raise SystemExit(0) from None
                raise
            if written == 0:
                raise SystemExit(0)
            remaining = remaining[written:]

    def _send(self, pixels):
        if self._closed:
            raise SystemExit(0)
        if not self._started and not self._allow_blank_first and pixels == _BLANK:
            return
        frame = (self._contrast, pixels)
        if frame == self._last_frame:
            return
        self._write(_PACKET.pack(FRAME if self._started else FIRST, *frame))
        self._last_frame = frame
        if not self._started:
            while True:
                try:
                    signal = os.read(self._resume_fd, 1)
                    break
                except InterruptedError:
                    continue
            if signal != b"G":
                raise SystemExit(0)
            self._started = True

    def _validate_image(self, image):
        if image.mode != self.mode or image.size != self.size:
            raise ValueError("Frame producer needs a monochrome 128x8 physical frame")

    def display_loading(self, image):
        """Leave preparation unblocked until the renderer has content to reveal."""
        self._validate_image(image)

    def display(self, image):
        self._validate_image(image)
        self._pixels = image.tobytes()
        self._send(_BLANK if self._hidden else self._pixels)

    def contrast(self, value):
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("Contrast must be an integer from 0 to 255")
        self._contrast = value
        if self._started and self._pixels is not None:
            self._send(_BLANK if self._hidden else self._pixels)

    def clear(self):
        self.display(Image.new(self.mode, self.size))

    def hide(self):
        self._hidden = True
        self._send(_BLANK)

    def show(self):
        self._hidden = False
        if self._pixels is not None:
            self._send(self._pixels)

    def cleanup(self):
        if not self._closed:
            self._closed = True
            for descriptor in (self._frame_fd, self._resume_fd):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
