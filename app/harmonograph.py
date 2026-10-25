"""The selected looping trace, with a bounded, dotted tail."""
from collections import deque
import math
import random

from PIL import Image, ImageDraw


class Harmonograph:
    def __init__(self, seed=7219):
        self.phase = random.Random(seed).uniform(0, math.tau)
        self.trail = deque(maxlen=180)
        self.next_sample = None

    def _point(self, t):
        x = 31.5 + 31.5 * math.sin(t * 0.7 + self.phase) * math.cos(t * 0.19)
        y = 7.5 + 7.5 * math.sin(t * 1.13 + self.phase * 0.5)
        return round(x), round(y)

    def render(self, t, dt):
        if self.next_sample is None:
            self.next_sample = max(0.0, t - dt)
        samples = 0
        while self.next_sample <= t and samples < 8:
            self.trail.append((self.next_sample, self._point(self.next_sample)))
            self.next_sample += 0.05
            samples += 1
        if self.next_sample <= t:
            self.next_sample = t + 0.05
        image = Image.new("1", (64, 16), 0)
        draw = ImageDraw.Draw(image)
        for index, (created, point) in enumerate(self.trail):
            age = t - created
            stride = 1 + int(max(0, age - 2) * 0.7)
            if (index + int(t * 0.8)) % stride == 0:
                draw.point(point, fill=1)
        draw.point(self._point(t), fill=1)
        return image


if __name__ == "__main__":
    from effect_runner import run
    run(Harmonograph())
