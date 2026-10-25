"""Three irregular sand streams filling a container with a central drain."""

import random

from PIL import Image

WIDTH = 64
HEIGHT = 16
SPOUTS = (10, 32, 54)
DROP_AREAS = tuple(tuple(range(center - 2, center + 3)) for center in SPOUTS)
STEP = 1 / 18
FULL_STEPS = 4
DRAIN = range(WIDTH // 2 - 4, WIDTH // 2 + 4)


class FallingSand:
    def __init__(self, seed=7219):
        self.rng = random.Random(seed)
        self.grid = bytearray(WIDTH * HEIGHT)
        self.grains = 0
        self.phase = "fill"
        self.gravity = 1
        self.completed_cycles = 0
        self.steps = 0
        self._draining_grains = 0
        self._full_steps = 0
        self._accumulator = 0.0

    def _move(self):
        if self.phase == "drain":
            self._funnel_floor()
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
                    grain = self.grid[source]
                    self.grid[source] = 0
                    self.grid[destination] = grain
        if self.phase == "drain":
            self._drain_outlet()

    def _open_drain(self):
        self.phase = "drain"
        # Tag the accumulated pile separately from fresh incoming grains, so
        # continuous pouring does not keep the plug open forever.
        self.grid[:] = bytes(1 if grain else 0 for grain in self.grid)
        self._draining_grains = self.grains

    def _drain_outlet(self):
        floor = (HEIGHT - 1) * WIDTH
        for x in DRAIN:
            index = floor + x
            grain = self.grid[index]
            if grain:
                self.grid[index] = 0
                self.grains -= 1
                if grain == 1:
                    self._draining_grains -= 1

    def _funnel_floor(self):
        floor = (HEIGHT - 1) * WIDTH
        # A funneling floor carries the last side piles toward the plug.
        # Traverse against motion so each floor grain moves at most one pixel.
        columns = (*range(DRAIN.start - 1, -1, -1), *range(DRAIN.stop, WIDTH))
        for x in columns:
            source = floor + x
            destination = source + (1 if x < DRAIN.start else -1)
            if self.grid[source] and not self.grid[destination]:
                self.grid[destination] = self.grid[source]
                self.grid[source] = 0

    def _emit(self):
        if self.grains == WIDTH * HEIGHT:
            return
        x = self.rng.choice(self.rng.choice(DROP_AREAS))
        if self.grid[x]:
            # A backed-up inlet spills along the top edge. Without overflow,
            # narrow drop areas jam before the corners can ever fill.
            open_columns = [column for column in range(WIDTH) if not self.grid[column]]
            if not open_columns:
                return
            distance = min(abs(column - x) for column in open_columns)
            x = self.rng.choice([column for column in open_columns if abs(column - x) == distance])
        self.grid[x] = 2 if self.phase == "drain" else 1
        self.grains += 1

    def _tick(self):
        if self.phase == "fill":
            self._move()
            self._emit()
            if self.grains == WIDTH * HEIGHT:
                # Keep the completely full image visible before it drains.
                self.phase = "full"
                self._full_steps = 0
        elif self.phase == "full":
            self._full_steps += 1
            if self._full_steps >= FULL_STEPS:
                self._open_drain()
        if self.phase == "drain":
            self._move()
            if self._draining_grains == 0:
                self.phase = "fill"
                self.completed_cycles += 1
            self._emit()

        self.steps += 1

    def render(self, t, dt):
        # Keep the original gentle falling speed and bound catch-up after pauses.
        self._accumulator = min(self._accumulator + max(0.0, dt), STEP * 6)
        while self._accumulator + 1e-12 >= STEP:
            previous_phase = self.phase
            self._tick()
            self._accumulator = max(0.0, self._accumulator - STEP)
            if self.phase == "full" and previous_phase != "full":
                # Always show the full panel, even during delayed-frame catch-up.
                self._accumulator = 0.0
                break
        image = Image.new("1", (WIDTH, HEIGHT), 0)
        image.putdata(self.grid)
        return image


if __name__ == "__main__":
    from effect_runner import run

    run(FallingSand())
