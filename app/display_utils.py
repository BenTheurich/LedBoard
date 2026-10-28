"""Pixel mapping and timing shared by the folded 64x16 display programs."""

import math
import time

from PIL import Image, ImageDraw

SWEEP_SECONDS = 1.2
TRANSITION_FPS = 40
STOP_TIMEOUT = 4


def sweep_position(progress):
    """One trajectory for the erase, loading and reveal bar."""
    return math.floor(max(0.0, min(1.0, progress)) * 72) - 4


def render_sweep(progress):
    """The same narrow bar and dithered edges throughout a mode change."""
    image = Image.new("1", (64, 16), 0)
    draw = ImageDraw.Draw(image)
    x = sweep_position(progress)
    draw.rectangle((x, 0, x + 2, 15), fill=1)
    for y in range(16):
        if 0 <= x - 1 < 64 and y % 2 == 0:
            draw.point((x - 1, y), fill=1)
        if 0 <= x + 3 < 64 and y % 2:
            draw.point((x + 3, y), fill=1)
    return image


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
