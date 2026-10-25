"""Three steady sand streams, with a full pile that slides down and out."""

import random

from PIL import Image

WIDTH = 64
HEIGHT = 16
SPOUTS = (10, 32, 54)
STEP = 1 / 18


class FallingSand:
    def __init__(self, seed=7219):
        self.rng = random.Random(seed)
        self.grid = bytearray(WIDTH * HEIGHT)
        self.grains = 0
        self.phase = "fill"
        self.gravity = 1
        self.completed_cycles = 0
        self.steps = 0
        self._drain_steps = 0
        self._accumulator = 0.0

    def _move(self):
        columns = range(WIDTH) if self.rng.random() < 0.5 else range(WIDTH - 1, -1, -1)
        # Bottom-to-top traversal moves each grain at most one row per step.
        for y in range(HEIGHT - 2, -1, -1):
            target_row = (y + 1) * WIDTH
            for x in columns:
                source = y * WIDTH + x
                if not self.grid[source]:
                    continue
                if not self.grid[target_row + x]:
                    destination = target_row + x
                else:
                    direction = -1 if self.rng.random() < 0.5 else 1
                    destination = None
                    for candidate in (x + direction, x - direction):
                        if 0 <= candidate < WIDTH and not self.grid[target_row + candidate]:
                            destination = target_row + candidate
                            break
                if destination is not None:
                    self.grid[source] = 0
                    self.grid[destination] = 1

    def _slide_down(self):
        self.grains -= sum(self.grid[-WIDTH:])
        self.grid[WIDTH:] = self.grid[:-WIDTH]
        self.grid[:WIDTH] = bytes(WIDTH)
        self._drain_steps += 1
        if self._drain_steps >= HEIGHT:
            # All pre-drain pixels have left. The newer stream grains remain.
            self.phase = "fill"
            self.completed_cycles += 1
            self._drain_steps = 0

    def _tick(self):
        if self.phase == "fill":
            self._move()
            # Test after movement, before emission: ordinary falling grains
            # briefly occupying the inlets must not trigger a drain.
            if all(self.grid[x] for x in SPOUTS):
                self.phase = "drain"
                self._drain_steps = 0
        if self.phase == "drain":
            self._slide_down()

        # Stagger the three fixed streams: six grains/second per spout.
        x = SPOUTS[self.steps % len(SPOUTS)]
        if not self.grid[x]:
            self.grid[x] = 1
            self.grains += 1
        self.steps += 1

    def render(self, t, dt):
        # Keep the original gentle falling speed and bound catch-up after pauses.
        self._accumulator = min(self._accumulator + max(0.0, dt), STEP * 6)
        while self._accumulator + 1e-12 >= STEP:
            self._tick()
            self._accumulator = max(0.0, self._accumulator - STEP)
        image = Image.new("1", (WIDTH, HEIGHT), 0)
        image.putdata(self.grid)
        return image


if __name__ == "__main__":
    from effect_runner import run

    run(FallingSand())
