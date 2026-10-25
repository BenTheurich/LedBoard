"""Two readable text rows on the folded 64 x 16 matrix."""

from functools import lru_cache

from PIL import Image, ImageDraw
from luma.core.legacy import text, textsize
from luma.core.legacy.font import TINY_FONT, proportional

_DEFAULT_FONT = proportional(TINY_FONT)


@lru_cache(maxsize=64)
def _line_image(line, font):
    # Rasterize once; marquee frames only crop pixels on the original Pi Zero.
    width, _ = textsize(line, font)
    strip = Image.new("1", (max(64, width), 8), 0)
    text(ImageDraw.Draw(strip), (0, 0), line, fill="white", font=font)
    return strip, width


def panel_duration(lines, font=None, minimum=4.0):
    """Allow the longest scrolling row to reach its end before changing cards."""
    font = font if font is not None else _DEFAULT_FONT
    distance = max((max(0, _line_image(line, font)[1] - 64) for line in lines[:2]), default=0)
    return max(minimum, 4.0 + distance / 12.0)


def render_lines(lines, elapsed=0.0, font=None):
    """Hold short rows still; pan long rows with a pause at either end."""
    font = font if font is not None else _DEFAULT_FONT
    image = Image.new("1", (64, 16), 0)
    for row, line in enumerate(lines[:2]):
        strip, width = _line_image(line, font)
        distance = max(0, width - 64)
        if distance:
            # Twelve pixels per second, with time to read the first and last words.
            travel = distance / 12.0
            phase = max(0.0, elapsed) % (travel + 4.0)
            offset = round(min(distance, max(0.0, phase - 2.0) * 12.0))
            image.paste(strip.crop((offset, 0, offset + 64, 8)), (0, row * 8))
        else:
            image.paste(strip.crop((0, 0, width, 8)), ((64 - width) // 2, row * 8))
    return image
