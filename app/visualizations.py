import random
import time
from PIL import Image, ImageDraw
from display_utils import FramePacer, map_serpentine

# --- LOGICAL DIMENSIONS ---
WIDTH = 64
HEIGHT = 16 

# --- ANIMATION 1: MATRIX RAIN ---
class MatrixRain:
    def __init__(self):
        self.drops = []
        for _ in range(20): 
            self.add_drop()
            
    def add_drop(self):
        self.drops.append({
            'x': random.randint(0, WIDTH-1),
            'y': random.randint(-HEIGHT, -1), 
            'speed': random.choice([0.5, 1, 1.5]) 
        })

    def step(self, elapsed):
        for drop in self.drops:
            drop['y'] += drop['speed'] * elapsed * 8
        
        # Remove drops that hit bottom and respawn
        self.drops = [d for d in self.drops if d['y'] < HEIGHT]
        while len(self.drops) < 20:
            self.add_drop()

    def draw(self, draw):
        for drop in self.drops:
            x = drop['x']
            y = int(drop['y'])
            # Draw trail
            if 0 <= y < HEIGHT: draw.point((x, y), fill="white")
            if 0 <= y-1 < HEIGHT: draw.point((x, y-1), fill="white")
            if 0 <= y-2 < HEIGHT and random.random() > 0.5: 
                draw.point((x, y-2), fill="white")

# --- ANIMATION 2: CYLON / KITT SCANNER ---
class CylonScanner:
    def __init__(self):
        self.x = 0
        self.direction = 1
        self.width = 8 

    def step(self, elapsed):
        self.x += self.direction * elapsed * 8
        if self.x + self.width >= WIDTH:
            self.x = WIDTH - self.width
            self.direction = -1
        if self.x <= 0:
            self.x = 0
            self.direction = 1

    def draw(self, draw):
        draw.rectangle((self.x, 0, self.x + self.width, HEIGHT-1), fill="white")

# --- ANIMATION 3: FAKE AUDIO SPECTRUM ---
class AudioSpectrum:
    def __init__(self):
        # Keep the relaxed original tempo while rendering intermediate frames.
        self.period = 1.0 / 8
        self.elapsed = 0.0
        self.bars = [random.randint(0, HEIGHT) for _ in range(WIDTH // 2)]
        self.targets = self.next_targets()

    def next_targets(self):
        return [max(0, min(HEIGHT, height + random.randint(-3, 3))) for height in self.bars]

    def step(self, elapsed):
        self.elapsed += elapsed
        # Tolerance avoids losing a step to fractional frame-interval rounding.
        while self.elapsed + 1e-12 >= self.period:
            self.bars = self.targets
            self.targets = self.next_targets()
            self.elapsed = max(0.0, self.elapsed - self.period)

    def draw(self, draw):
        progress = self.elapsed / self.period
        for i, (height, target) in enumerate(zip(self.bars, self.targets)):
            new_height = int(round(height + (target - height) * progress))
            
            x = i * 2
            
            # FIX: Only draw if the bar has height!
            if new_height > 0:
                # Draw from bottom (HEIGHT-1) upwards
                # y0 must be less than y1
                y_top = HEIGHT - new_height
                y_bottom = HEIGHT - 1
                
                draw.rectangle((x, y_top, x + 1, y_bottom), fill="white")

def main():
    from luma.core.interface.serial import spi, noop
    from luma.led_matrix.device import max7219

    serial = spi(port=0, device=0, gpio=noop())
    device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)
    device.contrast(16)
    mode = AudioSpectrum()
    print("Starting Visualizer...")
    pacer = FramePacer(25)
    previous = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            mode.step(now - previous)
            previous = now
            img = Image.new("1", (WIDTH, HEIGHT), 0)
            mode.draw(ImageDraw.Draw(img))
            device.display(map_serpentine(img))
            pacer.wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
