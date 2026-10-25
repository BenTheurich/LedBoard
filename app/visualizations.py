import time
import random
from PIL import Image, ImageDraw
from luma.core.interface.serial import spi, noop
from luma.led_matrix.device import max7219
from luma.core.render import canvas

# --- HARDWARE SETUP ---
serial = spi(port=0, device=0, gpio=noop())
# 16 Matrices (16x64 Serpentine)
device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)
device.contrast(16)

# --- LOGICAL DIMENSIONS ---
WIDTH = 64
HEIGHT = 16 

# --- RENDERER ---
def render_serpentine(device_draw, source_img):
    """
    Maps the 64x16 virtual image to your 16x64 Serpentine Layout.
    """
    for x in range(WIDTH):
        for y in range(HEIGHT):
            # Check pixel in virtual image
            if source_img.getpixel((x, y)) > 0:
                
                phys_x = x
                phys_y = y
                
                # --- MAPPING LOGIC ---
                # Top Row: Standard (y 0-7)
                if y < 8:
                    phys_x = x
                    phys_y = y
                    
                # Bottom Row: Serpentine & Flipped (y 8-15)
                elif y >= 8:
                    # 1. Reverse X (Right -> Left flow)
                    phys_x = 64 + (63 - x)
                    # 2. Reverse Y (Upside down board)
                    phys_y = 7 - (y - 8)

                if phys_x < 128:
                    device_draw.point((phys_x, phys_y), fill="white")

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

    def step(self):
        for drop in self.drops:
            drop['y'] += drop['speed']
        
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

    def step(self):
        self.x += self.direction
        if self.x + self.width >= WIDTH:
            self.direction = -1
        if self.x <= 0:
            self.direction = 1

    def draw(self, draw):
        draw.rectangle((self.x, 0, self.x + self.width, HEIGHT-1), fill="white")

# --- ANIMATION 3: FAKE AUDIO SPECTRUM ---
class AudioSpectrum:
    def __init__(self):
        # 32 bars, 2px wide each
        self.bars = [random.randint(0, HEIGHT) for _ in range(WIDTH // 2)] 

    def step(self):
        pass 

    def draw(self, draw):
        for i, height in enumerate(self.bars):
            # Jitter the height
            change = random.randint(-3, 3)
            # Clamp between 0 and 16
            new_height = max(0, min(HEIGHT, height + change))
            self.bars[i] = new_height
            
            x = i * 2
            
            # FIX: Only draw if the bar has height!
            if new_height > 0:
                # Draw from bottom (HEIGHT-1) upwards
                # y0 must be less than y1
                y_top = HEIGHT - new_height
                y_bottom = HEIGHT - 1
                
                draw.rectangle((x, y_top, x + 1, y_bottom), fill="white")

# --- MAIN SELECTION ---
# UNCOMMENT THE MODE YOU WANT
# mode = CylonScanner()
mode = AudioSpectrum()
# mode = MatrixRain()

print("Starting Visualizer...")

try:
    while True:
        # 1. Create a clean virtual image
        img = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(img)
        
        # 2. Update and Draw animation to virtual image
        if hasattr(mode, 'step'):
            mode.step()
        mode.draw(draw)
        
        # 3. Map virtual image to physical hardware
        with canvas(device) as device_draw:
            render_serpentine(device_draw, img)
            
        time.sleep(0.04)

except KeyboardInterrupt:
    pass
