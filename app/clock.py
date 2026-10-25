import time
import datetime
from PIL import Image, ImageDraw
from luma.core.interface.serial import spi, noop
from luma.led_matrix.device import max7219
from luma.core.render import canvas
from luma.core.legacy import text, textsize
from luma.core.legacy.font import proportional, CP437_FONT

# --- HARDWARE SETUP ---
serial = spi(port=0, device=0, gpio=noop())
# 16 Matrices (Standard 128x8 physical strip, folded to 64x16)
device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)
device.contrast(32)

# --- LOGICAL DIMENSIONS ---
WIDTH = 64
HEIGHT = 16

def render_serpentine(device_draw, source_img):
    """
    Maps the 64x16 virtual image to your 16x64 Serpentine Layout.
    """
    for x in range(WIDTH):
        for y in range(HEIGHT):
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

# --- MAIN LOOP ---
print("Starting Stretch Clock...")

try:
    font = proportional(CP437_FONT)

    while True:
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")

        # 1. Measure the text
        w, h = textsize(time_str, font)
        
        # 2. Create a tiny image just for the text (standard 8px high)
        # We add a little padding to width to be safe
        tiny_img = Image.new("1", (w, 8), 0)
        tiny_draw = ImageDraw.Draw(tiny_img)
        text(tiny_draw, (0, 0), time_str, fill="white", font=font)

        # 3. THE TRICK: STRETCH IT
        # We resize the 8px high image to 16px high using "Nearest Neighbor"
        # This keeps the sharp pixel look but makes it tall.
        stretched_img = tiny_img.resize((w, 16), resample=Image.NEAREST)

        # 4. Paste it into the center of our main canvas
        main_img = Image.new("1", (WIDTH, HEIGHT), 0)
        
        # Calculate X center
        x_pos = (WIDTH - w) // 2
        # Y pos is 0 because we filled the whole 16px height
        main_img.paste(stretched_img, (x_pos, 0))
        
        # 5. Render
        with canvas(device) as device_draw:
            render_serpentine(device_draw, main_img)
            
        time.sleep(0.05)

except KeyboardInterrupt:
    with canvas(device) as draw:
        pass
