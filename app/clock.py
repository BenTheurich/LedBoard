import datetime
import time

from PIL import Image, ImageDraw

from display_utils import map_serpentine


def render_clock_image(time_str, font):
    """Keep digit cells and separators fixed as the displayed time changes."""
    from luma.core.legacy import text, textsize

    digit_width = max(textsize(digit, font)[0] for digit in "0123456789")
    colon_width, _ = textsize(":", font)
    width = 6 * digit_width + 2 * colon_width
    tiny = Image.new("1", (width, 8), 0)
    draw = ImageDraw.Draw(tiny)
    x = 0
    for character in time_str:
        cell_width = colon_width if character == ":" else digit_width
        glyph_width, _ = textsize(character, font)
        text(draw, (x + (cell_width - glyph_width) // 2, 0), character,
             fill="white", font=font)
        x += cell_width
    stretched = tiny.resize((width, 16), resample=Image.Resampling.NEAREST)
    image = Image.new("1", (64, 16), 0)
    image.paste(stretched, ((64 - width) // 2, 0))
    return image


def run_clock(device, font):
    last_text = None
    while True:
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        if time_str != last_text:
            device.display(map_serpentine(render_clock_image(time_str, font)))
            last_text = time_str
        # Calculate after rendering so its duration does not shift the next tick.
        time.sleep(max(0.001, 1.0 - time.time() % 1.0))


def main():
    # Keep hardware initialization out of imports used by desktop tests.
    from luma.core.interface.serial import spi, noop
    from luma.core.legacy.font import proportional, CP437_FONT
    from luma.led_matrix.device import max7219

    serial = spi(port=0, device=0, gpio=noop())
    device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)
    device.contrast(32)
    print("Starting Stretch Clock...")
    try:
        run_clock(device, proportional(CP437_FONT))
    except KeyboardInterrupt:
        device.clear()


if __name__ == "__main__":
    main()
