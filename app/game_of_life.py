import time
import random
import copy 
from luma.core.interface.serial import spi, noop
from luma.led_matrix.device import max7219
from luma.core.render import canvas

# --- HARDWARE SETUP ---
serial = spi(port=0, device=0, gpio=noop())

# UPDATE: cascaded=16 (4 boards x 4 matrices)
# The Pi sees this as a strip 128 pixels wide and 8 pixels high.
device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)

# --- SAFETY SETTINGS ---
# Keep contrast low (10-16) to prevent power crashes
device.contrast(32)  
SPEED = 0.05          

# --- LOGICAL DIMENSIONS ---
# We simulate a 16x64 grid
WIDTH = 64
HEIGHT = 16 

# --- FLUSH ROUTINE ---
# Clears garbage data from registers on startup to prevent "freak outs"
print("Flushing display memory...")
with canvas(device) as draw:
    draw.rectangle(device.bounding_box, fill="black")
time.sleep(1.0)
print("Display cleared. Starting simulation...")

class GameOfLife:
    def __init__(self, w, h):
        self.width = w
        self.height = h
        self.grid = []
        self.history = [] 
        self.reset()

    def reset(self):
        self.grid = [[random.choice([0, 1]) for _ in range(self.height)] for _ in range(self.width)]
        self.history = [] 

    def count_neighbors(self, x, y):
        count = 0
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0: continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    count += self.grid[nx][ny]
        return count

    def step(self):
        self.history.append(copy.deepcopy(self.grid))
        if len(self.history) > 4:
            self.history.pop(0)

        new_grid = [[0 for _ in range(self.height)] for _ in range(self.width)]
        changes = 0
        alive_count = 0

        for x in range(self.width):
            for y in range(self.height):
                neighbors = self.count_neighbors(x, y)
                state = self.grid[x][y]
                
                if state == 1 and (neighbors == 2 or neighbors == 3):
                    new_grid[x][y] = 1
                    alive_count += 1
                elif state == 0 and neighbors == 3:
                    new_grid[x][y] = 1
                    changes += 1
                    alive_count += 1
                else:
                    new_grid[x][y] = 0
                    if state == 1:
                        changes += 1

        self.grid = new_grid
        return changes, alive_count

    def is_stuck_in_loop(self):
        if len(self.history) >= 2:
            if self.grid == self.history[-2]: return True
        if len(self.history) >= 3:
            if self.grid == self.history[-3]: return True
        return False

    def draw(self, draw_obj):
        """
        Translates the 16x64 Logical Grid to the SERPENTINE Physical Chain.
        """
        for x in range(self.width):
            for y in range(self.height):
                if self.grid[x][y] == 1:
                    
                    phys_x = x
                    phys_y = y
                    
                    # --- TOP ROW (Standard) ---
                    if y < 8:
                        phys_x = x
                        phys_y = y

                    # --- BOTTOM ROW (Serpentine & Flipped) ---
                    elif y >= 8:
                        # 1. THE SNAKE: Reverse the X order
                        # Logical X=63 (Right) becomes the START of the bottom chain (Phys 64)
                        phys_x = 64 + (63 - x)
                        
                        # 2. THE FLIP: Reverse the Y order
                        # Since the board is upside down, we invert Y so up is up.
                        phys_y = 7 - (y - 8)

                    # Only draw if the pixel physically exists
                    # (Limit is now 128 because you have 16 matrices)
                    if phys_x < 128:
                        draw_obj.point((phys_x, phys_y), fill="white")

# --- MAIN LOOP ---
game = GameOfLife(WIDTH, HEIGHT)

try:
    while True:
        with canvas(device) as draw:
            game.draw(draw)
        
        changes, alive_count = game.step()
        
        # Reset if empty, still, or stuck in a loop
        if alive_count == 0 or changes == 0 or game.is_stuck_in_loop():
            print("Simulation ended. Resetting...")
            with canvas(device) as draw:
                draw.rectangle(device.bounding_box, fill="black")
            time.sleep(1.0) 
            game.reset()
        
        time.sleep(SPEED)

except KeyboardInterrupt:
    with canvas(device) as draw:
        draw.rectangle(device.bounding_box, fill="black")
    print("\nClean exit.")
