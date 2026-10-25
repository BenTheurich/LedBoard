"""Classic falling code, sized for the monochrome 64x16 display."""

from dataclasses import dataclass
import math
import random

from PIL import Image, ImageDraw


WIDTH = 64
HEIGHT = 16
STREAM_COUNT = 16
LANE_PITCH = 4
GLYPH_HEIGHT = 5
GLYPH_PITCH = 6
STEP = 1.0 / 40
MAX_CATCHUP_STEPS = 10

# Tiny digits and symbols remain recognizable at three pixels wide.
GLYPHS = (
    (0b111, 0b101, 0b101, 0b101, 0b111),  # 0
    (0b010, 0b110, 0b010, 0b010, 0b111),  # 1
    (0b111, 0b001, 0b111, 0b100, 0b111),  # 2
    (0b111, 0b001, 0b111, 0b001, 0b111),  # 3
    (0b101, 0b101, 0b111, 0b001, 0b001),  # 4
    (0b111, 0b100, 0b111, 0b001, 0b111),  # 5
    (0b111, 0b100, 0b111, 0b101, 0b111),  # 6
    (0b111, 0b001, 0b010, 0b010, 0b010),  # 7
    (0b111, 0b101, 0b111, 0b101, 0b111),  # 8
    (0b111, 0b101, 0b111, 0b001, 0b111),  # 9
    (0b000, 0b010, 0b111, 0b010, 0b000),  # +
    (0b000, 0b111, 0b000, 0b111, 0b000),  # =
    (0b001, 0b010, 0b100, 0b010, 0b001),  # <
    (0b100, 0b010, 0b001, 0b010, 0b100),  # >
    (0b000, 0b010, 0b000, 0b010, 0b000),  # :
)
DENSE_GLYPHS = tuple(glyph for glyph in GLYPHS if sum(row.bit_count() for row in glyph) >= 12)


@dataclass
class _Stream:
    x: int
    y: float
    speed: float
    glyphs: tuple
    pattern: int


class AcidRain:
    def __init__(self, seed=7219):
        self.rng = random.Random(seed)
        self.pending = 0.0
        self.streams = [self._new_stream(index, initial=True) for index in range(STREAM_COUNT)]

    def _new_stream(self, lane, initial=False):
        y = self.rng.uniform(-HEIGHT, HEIGHT - 1) if initial else -self.rng.uniform(GLYPH_HEIGHT, HEIGHT + 8)
        if initial and lane == 0:
            y = self.rng.uniform(0, HEIGHT - GLYPH_HEIGHT)
        count = self.rng.randrange(2, 5)
        glyphs = (self.rng.choice(DENSE_GLYPHS),) + tuple(
            self.rng.choice(GLYPHS) for _ in range(count - 1)
        )
        return _Stream(lane * LANE_PITCH, y, self.rng.uniform(4, 9),
                       glyphs, self.rng.randrange(4))

    def _step(self):
        for lane, stream in enumerate(self.streams):
            stream.y += stream.speed * STEP
            # The last trailing glyph exits naturally before the lane restarts.
            if stream.y - (len(stream.glyphs) - 1) * GLYPH_PITCH >= HEIGHT:
                self.streams[lane] = self._new_stream(lane)

    def render(self, t, dt):
        # A delayed frame must not replay a long backlog of animation updates.
        self.pending = min(self.pending + max(0.0, dt), STEP * MAX_CATCHUP_STEPS)
        while self.pending + 1e-12 >= STEP:
            self._step()
            self.pending = max(0.0, self.pending - STEP)

        image = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(image)
        for stream in self.streams:
            head = math.floor(stream.y)
            for index, glyph in enumerate(stream.glyphs):
                top = head - index * GLYPH_PITCH
                for gy, row in enumerate(glyph):
                    y = top + gy
                    if not 0 <= y < HEIGHT:
                        continue
                    for gx in range(3):
                        if not row & (1 << (2 - gx)):
                            continue
                        # Fixed spatial dithering suggests dimmer tails without
                        # temporal flicker or per-pixel brightness support.
                        keep = (index == 0
                                or (index == 1 and (gx + gy + stream.pattern) % 4 != 0)
                                or (index == 2 and (gx + gy + stream.pattern) % 2 == 0)
                                or (index == 3 and (gx + 2 * gy + stream.pattern) % 4 == 0))
                        if keep:
                            draw.point((stream.x + gx, y), fill=1)
        return image


if __name__ == "__main__":
    from effect_runner import run

    run(AcidRain())
