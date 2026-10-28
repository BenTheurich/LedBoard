"""Pixel mapping and timing shared by the folded 64x16 display programs."""

import time

from PIL import Image

SWEEP_SECONDS = 0.45
TRANSITION_FPS = 40


def map_serpentine(image):
    """Map a logical 64x16 image onto the physical 128x8 matrix chain."""
    physical = Image.new("1", (128, 8), 0)
    physical.paste(image.crop((0, 0, 64, 8)), (0, 0))
    # The lower row of boards runs backwards and is mounted upside down.
    bottom = image.crop((0, 8, 64, 16)).transpose(Image.Transpose.ROTATE_180)
    physical.paste(bottom, (64, 0))
    return physical


class FramePacer:
    """Include rendering time in each frame period without catch-up bursts."""

    def __init__(self, fps):
        self._period = 1.0 / fps
        self._deadline = time.monotonic()

    def wait(self):
        self._deadline += self._period
        now = time.monotonic()
        remaining = self._deadline - now
        if remaining > 0:
            time.sleep(remaining)
        else:
            # A late frame starts a fresh schedule instead of accumulating debt.
            self._deadline = now
