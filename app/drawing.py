"""Show a hand-drawn monochrome image on the 64 x 16 matrix."""

import argparse

from PIL import Image

WIDTH, HEIGHT = 64, 16
PIXEL_COUNT = WIDTH * HEIGHT


def validate_pixels(value):
    """The wire format is exactly 1,024 row-major bits, top-left first."""
    if not isinstance(value, str) or len(value) != PIXEL_COUNT or set(value) - {"0", "1"}:
        raise ValueError("Send exactly 1,024 pixels, each 0 (off) or 1 (on).")
    return value


class DrawingDisplay:
    def __init__(self, pixels):
        packed = int(validate_pixels(pixels), 2).to_bytes(PIXEL_COUNT // 8, "big")
        self.image = Image.frombytes("1", (WIDTH, HEIGHT), packed)

    def render(self, elapsed, delta):
        return self.image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pixels", required=True)
    args = parser.parse_args()
    try:
        display = DrawingDisplay(args.pixels)
    except ValueError as error:
        parser.error(str(error))
    from effect_runner import run
    run(display)


if __name__ == "__main__":
    main()
