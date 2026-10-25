"""Sparse Matrix-style rain for the monochrome 64x16 display."""

from collections import deque
from dataclasses import dataclass
import random

from PIL import Image, ImageDraw


WIDTH = 64
HEIGHT = 16
DROP_COUNT = 16
MAX_SPLASHES = 24
STEP = 1.0 / 40


@dataclass
class _Drop:
    x: int
    y: float
    speed: float
    length: int
    pattern: int


@dataclass
class _Splash:
    x: int
    age: float
    lifetime: float
    side: int


class AcidRain:
    def __init__(self, seed=7219):
        self.rng = random.Random(seed)
        self.pending = 0.0
        self.drops = [self._new_drop(index, initial=True) for index in range(DROP_COUNT)]
        self.splashes = deque(maxlen=MAX_SPLASHES)

    def _new_drop(self, index, initial=False):
        # One stream per four-column band avoids both large gaps and dense clumps.
        start = index * WIDTH // DROP_COUNT
        stop = (index + 1) * WIDTH // DROP_COUNT
        y = self.rng.uniform(-HEIGHT, HEIGHT - 1) if initial else -self.rng.uniform(2, 12)
        if initial and index == 0:
            y = self.rng.uniform(2, HEIGHT - 3)
        return _Drop(self.rng.randrange(start, stop), y,
                     self.rng.uniform(6, 14), self.rng.randrange(4, 8),
                     self.rng.randrange(4))

    def _step(self):
        for splash in self.splashes:
            splash.age += STEP
        self.splashes = deque((splash for splash in self.splashes
                               if splash.age < splash.lifetime), maxlen=MAX_SPLASHES)

        for index, drop in enumerate(self.drops):
            previous = drop.y
            drop.y += drop.speed * STEP
            if previous < HEIGHT <= drop.y:
                self.splashes.append(_Splash(drop.x, 0.0, self.rng.uniform(0.65, 1.0),
                                             self.rng.choice((-1, 1))))
            # Let the dotted tail leave the screen before reusing its stream.
            if drop.y - drop.length >= HEIGHT:
                self.drops[index] = self._new_drop(index)

    def render(self, t, dt):
        # Fixed-size logical steps keep the speed stable across rendering rates.
        # A delayed frame must not replay seconds of rain before responding.
        self.pending = min(self.pending + max(0.0, dt), STEP * 10)
        while self.pending + 1e-12 >= STEP:
            self._step()
            self.pending = max(0.0, self.pending - STEP)

        image = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(image)
        for drop in self.drops:
            head = int(drop.y)
            for offset in range(drop.length):
                y = head - offset
                if 0 <= y < HEIGHT and (offset < 2 or (offset + drop.pattern) % 2 == 0):
                    draw.point((drop.x, y), fill=1)
            # A few short crossbars suggest code fragments without needing glyphs.
            if drop.pattern == 0 and 1 <= head < HEIGHT:
                draw.point((min(WIDTH - 1, drop.x + 1), head - 1), fill=1)

        for splash in self.splashes:
            phase = splash.age / splash.lifetime
            if phase < 0.3:
                points = ((splash.x, 15), (splash.x - 1, 14), (splash.x + 1, 14))
            elif phase < 0.65:
                points = ((splash.x - 1, 15), (splash.x + 1, 15))
            else:
                points = ((splash.x + splash.side, 15),)
            for x, y in points:
                if 0 <= x < WIDTH:
                    draw.point((x, y), fill=1)
        return image


if __name__ == "__main__":
    from effect_runner import run

    run(AcidRain())
