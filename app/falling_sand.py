"""A finite sand cycle: pour, reverse gravity, drain, and begin empty again."""

import random

from PIL import Image

WIDTH = 64
HEIGHT = 16
STEP = 1 / 24
TARGET_GRAINS = 384


class FallingSand:
    def __init__(self, seed=7219):
        self.rng = random.Random(seed)
        self.grid = bytearray(WIDTH * HEIGHT)
        self.grains = 0
        self.phase = "empty"
        self.gravity = 1
        self.completed_cycles = 0
        self._phase_steps = 0
        self._accumulator = 0.0

    def _enter(self, phase, gravity=1):
        self.phase = phase
        self.gravity = gravity
        self._phase_steps = 0

    def _move(self):
        rows = range(HEIGHT - 2, -1, -1) if self.gravity > 0 else range(1, HEIGHT)
        columns = range(WIDTH) if self.rng.random() < 0.5 else range(WIDTH - 1, -1, -1)
        for y in rows:
            target_row = (y + self.gravity) * WIDTH
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

    def _emit(self, start):
        if self.grains >= TARGET_GRAINS:
            return
        # Sweep the inlet, then try other open columns if a pile blocks it.
        for offset in range(WIDTH):
            x = (start + offset) % WIDTH
            if not self.grid[x]:
                self.grid[x] = 1
                self.grains += 1
                return

    def _drain(self):
        # Eventually open the entire floor: no isolated pile can remain stuck.
        width = min(WIDTH, 4 + 4 * (self._phase_steps // 8))
        left = (WIDTH - width) // 2
        for x in range(left, left + width):
            index = (HEIGHT - 1) * WIDTH + x
            if self.grid[index]:
                self.grid[index] = 0
                self.grains -= 1

    def _tick(self):
        self._phase_steps += 1
        if self.phase == "empty":
            if self._phase_steps >= 24:
                self._enter("pour")
            return

        if self.phase == "drain":
            self._drain()
        self._move()

        if self.phase == "pour":
            sweep = self._phase_steps % (2 * WIDTH - 2)
            x = sweep if sweep < WIDTH else 2 * WIDTH - 2 - sweep
            self._emit(x)
            self._emit((x + 1) % WIDTH)
            if self.grains >= TARGET_GRAINS:
                self._enter("settle")
        elif self.phase == "settle" and self._phase_steps >= 24:
            self._enter("reverse_up", -1)
        elif self.phase == "reverse_up" and self._phase_steps >= 72:
            self._enter("reverse_down")
        elif self.phase == "reverse_down" and self._phase_steps >= 72:
            self._enter("drain")
        elif self.phase == "drain" and self.grains == 0:
            self.completed_cycles += 1
            self._enter("empty")

    def render(self, t, dt):
        # Fixed simulation steps keep the flow consistent across render rates;
        # a delayed frame does at most six steps instead of a catch-up burst.
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
