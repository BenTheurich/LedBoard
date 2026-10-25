"""Single-column falling pixels for the monochrome 64x16 display."""

from dataclasses import dataclass
import random

from PIL import Image, ImageDraw


WIDTH = 64
HEIGHT = 16
DROP_COUNT = 16
STEP = 1.0 / 40
MAX_CATCHUP_STEPS = 10


@dataclass
class _Drop:
    x: int
    y: float
    speed: float
    length: int
    pattern: int


class AcidRain:
    def __init__(self, seed=7219):
        self.rng = random.Random(seed)
        self.pending = 0.0
        self.drops = [self._new_drop(index, initial=True) for index in range(DROP_COUNT)]

    def _new_drop(self, index, initial=False):
        # Keep the original staggered positions within four-column bands.
        start = index * WIDTH // DROP_COUNT
        stop = (index + 1) * WIDTH // DROP_COUNT
        y = self.rng.uniform(-HEIGHT, HEIGHT - 1) if initial else -self.rng.uniform(2, 12)
        if initial and index == 0:
            y = self.rng.uniform(2, HEIGHT - 3)
        return _Drop(self.rng.randrange(start, stop), y,
                     self.rng.uniform(6, 14), self.rng.randrange(4, 8),
                     self.rng.randrange(4))

    def _step(self):
        for index, drop in enumerate(self.drops):
            drop.y += drop.speed * STEP
            # Nothing reacts at the bottom: the complete tail simply passes out.
            if drop.y - (drop.length - 1) >= HEIGHT:
                self.drops[index] = self._new_drop(index)

    def render(self, t, dt):
        # A delayed frame must not replay a long backlog of animation updates.
        self.pending = min(self.pending + max(0.0, dt), STEP * MAX_CATCHUP_STEPS)
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
        return image


if __name__ == "__main__":
    from effect_runner import run

    run(AcidRain())
