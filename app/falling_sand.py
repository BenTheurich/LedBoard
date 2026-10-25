"""Synchronous sand grains, with three inlets and a central drain."""

import random

from PIL import Image

WIDTH = 64
HEIGHT = 16
CELLS = WIDTH * HEIGHT
SPOUTS = (10, 32, 54)
DROP_AREAS = tuple(tuple(range(center - 2, center + 3)) for center in SPOUTS)
STEP = 1 / 18
DRAIN_STEP = STEP / 2
FULL_STEPS = 4
DRAIN = range(WIDTH // 2 - 1, WIDTH // 2 + 1)
DRAIN_GROW_STEPS = 12
ALL = (1 << CELLS) - 1
BOTTOM = ((1 << WIDTH) - 1) << (WIDTH * (HEIGHT - 1))
LEFT = sum(1 << (row * WIDTH) for row in range(HEIGHT))
RIGHT = LEFT << (WIDTH - 1)
# Pillow's packed pixels are most-significant-bit first within each byte.
REVERSE_BITS = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))


def _shift(bits, amount):
    return bits << amount if amount >= 0 else bits >> -amount


class FallingSand:
    def __init__(self, seed=7219):
        self.rng = random.Random(seed)
        self._sand = 0
        self.grains = 0
        self.phase = "fill"
        self.gravity = 1
        self.completed_cycles = 0
        self.steps = 0
        self._full_steps = 0
        self._accumulator = 0.0
        self._drain_steps = 0
        self._widen_drain()

    @property
    def drain_width(self):
        return self._drain_radius * 2 if self.phase == "drain" else 0

    @property
    def grid(self):
        """Return a fixture/debug snapshot; rendering uses packed bits directly."""
        return bytearray((self._sand >> index) & 1 for index in range(CELLS))

    @grid.setter
    def grid(self, values):
        if len(values) != CELLS or any(value not in (0, 1) for value in values):
            raise ValueError("Grid must contain 1024 empty/occupied cells")
        self._sand = sum(1 << index for index, value in enumerate(values) if value)
        self.grains = self._sand.bit_count()

    def _move(self):
        snapshot = self._sand
        empty = ALL ^ snapshot
        remaining = snapshot
        result = snapshot
        claimed = 0

        def move(amount, allowed):
            nonlocal remaining, result, claimed
            # Only cells empty in the original frame may receive a grain.
            # Claims prevent two diagonals merging into the same destination.
            sources = remaining & allowed & _shift(empty & ~claimed, -amount)
            destinations = _shift(sources, amount)
            result = (result & ~sources) | destinations
            claimed |= destinations
            remaining &= ~sources

        move(WIDTH, ALL ^ BOTTOM)
        preference = self.rng.getrandbits(CELLS)
        diagonals = ((WIDTH - 1, ALL & ~BOTTOM & ~LEFT, preference),
                     (WIDTH + 1, ALL & ~BOTTOM & ~RIGHT, ALL ^ preference))
        if self.rng.getrandbits(1):
            diagonals = diagonals[::-1]
        for amount, allowed, preferred in diagonals:
            move(amount, allowed & preferred)
        for amount, allowed, _ in diagonals:
            move(amount, allowed)

        if self.phase == "drain":
            result &= ~self._outlet
        self._sand = result
        self.grains = result.bit_count()

    def _open_drain(self):
        self.phase = "drain"
        self._drain_steps = 0
        self._widen_drain()

    def _widen_drain(self):
        self._drain_radius = min(WIDTH // 2, 1 + self._drain_steps // DRAIN_GROW_STEPS)
        start = WIDTH // 2 - self._drain_radius
        opening = (1 << (self._drain_radius * 2)) - 1
        self._outlet = opening << ((HEIGHT - 1) * WIDTH + start)

    def _emit(self):
        if self.grains == CELLS:
            return
        x = self.rng.choice(self.rng.choice(DROP_AREAS))
        if self._sand >> x & 1:
            # A backed-up inlet overflows to the nearest open top position.
            open_columns = [column for column in range(WIDTH) if not self._sand >> column & 1]
            if not open_columns:
                return
            distance = min(abs(column - x) for column in open_columns)
            x = self.rng.choice([column for column in open_columns if abs(column - x) == distance])
        bit = 1 << x
        self._sand |= bit
        self.grains += 1

    def _tick(self):
        if self.phase == "fill":
            self._move()
            self._emit()
            if self.grains == CELLS:
                self.phase = "full"
                self._full_steps = 0
        elif self.phase == "full":
            self._full_steps += 1
            if self._full_steps >= FULL_STEPS:
                self._open_drain()
        if self.phase == "drain":
            self._widen_drain()
            self._move()
            self._drain_steps += 1
            if self.grains == 0:
                self.phase = "fill"
                self.completed_cycles += 1
        self.steps += 1

    def render(self, t, dt):
        interval = DRAIN_STEP if self.phase == "drain" else STEP
        self._accumulator = min(self._accumulator + max(0.0, dt), interval * 6)
        for _ in range(6):
            interval = DRAIN_STEP if self.phase == "drain" else STEP
            if self._accumulator + 1e-12 < interval:
                break
            previous_phase = self.phase
            self._tick()
            self._accumulator = max(0.0, self._accumulator - interval)
            if ((self.phase == "full" and previous_phase != "full")
                    or (previous_phase == "drain" and self.phase == "fill")):
                # Always return the full and empty boundary images to the viewer.
                self._accumulator = 0.0
                break
        packed = self._sand.to_bytes(CELLS // 8, "little").translate(REVERSE_BITS)
        return Image.frombytes("1", (WIDTH, HEIGHT), packed)


if __name__ == "__main__":
    from effect_runner import run

    run(FallingSand())
