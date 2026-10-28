import time
from datetime import datetime
from luma.core.legacy import text, textsize
from luma.core.legacy.font import proportional, CP437_FONT
from PIL import Image, ImageDraw
from display_utils import FramePacer, map_serpentine

# --- CONFIGURATION ---
SEARCH_NAME = "Garching, Untere Straßäcker"
TARGET_DEST = "Forschungszentrum"
TARGET_LINES = ["230", "292", "X205"]

# --- BRIGHTNESS SETTINGS ---
BRIGHTNESS_DAY = 32   
BRIGHTNESS_NIGHT = 10 
HOUR_DAY_START = 7    
HOUR_NIGHT_START = 20 

# --- ANIMATION SETTINGS ---
SCROLL_SPEED = 0.05    # One pixel every 50 ms, including rendering time
PAUSE_AT_ROWS = 10.0   # Reading time while advancing through departures

# --- HARDWARE ---
device = None  # Initialized only when this script runs on the Pi.

# Logical Dimensions
WIDTH = 64
ROW_HEIGHT = 8
HEIGHT = 2 * ROW_HEIGHT

found_station_id = None 

# --- HELPER FUNCTIONS ---

def check_brightness():
    now = datetime.now()
    if HOUR_DAY_START <= now.hour < HOUR_NIGHT_START:
        device.contrast(BRIGHTNESS_DAY)
    else:
        device.contrast(BRIGHTNESS_NIGHT)

def get_departures():
    from mvg import MvgApi

    global found_station_id
    try:
        if found_station_id is None:
            print(f"Searching for '{SEARCH_NAME}'...")
            station = MvgApi.station(SEARCH_NAME)
            if station:
                found_station_id = station['id']
            else:
                return []

        mvg_station = MvgApi(found_station_id)
        departures = mvg_station.departures()
        
        next_busses = []
        now_ts = time.time()
        
        for dep in departures:
            line_name = dep.get('line')       
            destination = dep.get('destination', '')
            timestamp = dep.get('time', 0)    
            
            if (line_name in TARGET_LINES and 
                TARGET_DEST.lower() in destination.lower()):
                
                minutes = int((timestamp - now_ts) / 60)
                if minutes < 0: continue 
                
                # Symmetry Fix: Rename X205 to 205
                display_name = line_name
                if display_name == "X205":
                    display_name = "205"
                
                time_str = f"{minutes}m"
                next_busses.append((f"{display_name}:", time_str))
                
                # Limit to 8 buses (enough to scroll nicely)
                if len(next_busses) >= 8: 
                    break
                    
        return next_busses

    except Exception as e:
        print(f"API Error: {e}")
        found_station_id = None 
        return []

def render_bus_image(bus_data):
    """Creates a static 64x8 image for a single bus with DOTS."""
    font = proportional(CP437_FONT)
    img = Image.new("1", (64, 8))
    draw = ImageDraw.Draw(img)
    
    # Handle "No Bus" or simple messages
    if isinstance(bus_data, str):
        text_to_show = bus_data
        w, h = textsize(text_to_show, font=font)
        x_pos = (64 - w) // 2 
        text(draw, (x_pos, 0), text_to_show, fill="white", font=font)
        return img

    label, minutes_str = bus_data
    
    # 1. Draw Name (Left)
    text(draw, (0, 0), label, fill="white", font=font)
    w_label, h = textsize(label, font=font)
    
    # 2. Draw Time (Right)
    w_time, h = textsize(minutes_str, font=font)
    x_time = 64 - w_time
    text(draw, (x_time, 0), minutes_str, fill="white", font=font)
    
    # 3. Draw The Dots
    # Start after the label, end before the time
    dot_start = w_label + 3
    dot_end = x_time - 3
    
    # Draw a pixel every 3 steps at y=6 (near the baseline)
    if dot_end > dot_start:
        for x in range(dot_start, dot_end, 3):
            draw.point((x, 6), fill="white")
            
    return img

def create_tall_scroll_image(bus_list):
    """
    Stitches multiple 64x8 bus images into one tall vertical image.
    """
    # Ensure at least 2 lines so screen isn't half empty
    if not bus_list:
        bus_list = ["No Bus Found", ""]
    elif len(bus_list) == 1:
        bus_list = [*bus_list, ""]  # Keep the caller's departure list unchanged.
        
    num_lines = len(bus_list)
    virtual_height = num_lines * ROW_HEIGHT
    
    # Create the tall canvas
    master_img = Image.new("1", (WIDTH, virtual_height), 0)
    
    for i, bus_data in enumerate(bus_list):
        # Generate the single line image (with dots etc)
        line_img = render_bus_image(bus_data)
        
        # Paste it into the master image at the correct Y offset
        # Line 0 goes at y=0, Line 1 goes at y=8, etc.
        master_img.paste(line_img, (0, i * ROW_HEIGHT))
        
    return master_img, virtual_height

def show_window(source_img, scroll_y):
    """Crop the visible rows and send the folded image to the matrix chain."""
    window = source_img.crop((0, scroll_y, WIDTH, scroll_y + HEIGHT))
    device.display(map_serpentine(window))

def run_vertical_scroll(bus_list):
    """Pause through the departures, then reset to the top without row stops."""
    
    # 1. Create the tall image containing all buses
    tall_image, tall_height = create_tall_scroll_image(bus_list)
    
    # Calculate how far we can scroll
    # If we have 4 lines (32px), and screen is 16px, we scroll 16px.
    max_scroll = tall_height - HEIGHT
    if max_scroll < 0: max_scroll = 0
    pacer = FramePacer(1.0 / SCROLL_SPEED)
    
    # 2. SCROLL DOWN
    for y in range(0, max_scroll + 1):
        show_window(tall_image, y)
        
        if y % ROW_HEIGHT == 0:
            time.sleep(PAUSE_AT_ROWS)
            # Resume a steady cadence after reading instead of catching up.
            pacer = FramePacer(1.0 / SCROLL_SPEED)
        else:
            pacer.wait()
    
    # 3. SCROLL UP
    # The return is a continuous reset; reading pauses belong only to the first pass.
    for y in range(max_scroll - 1, -1, -1):
        show_window(tall_image, y)
        if y > 0:
            pacer.wait()

def main():
    global device
    from luma.core.interface.serial import spi, noop
    from luma.led_matrix.device import max7219

    device = max7219(spi(port=0, device=0, gpio=noop()), cascaded=16,
                     block_orientation=-90, rotate=0)
    device.contrast(BRIGHTNESS_DAY)
    print(f"Starting 2-Row Bus Scroll... Day: {BRIGHTNESS_DAY} / Night: {BRIGHTNESS_NIGHT}")
    # Give feedback before the transit client import and first network request.
    loading, _ = create_tall_scroll_image(["BUS", "LOADING"])
    show_window(loading, 0)
    try:
        while True:
            check_brightness()
            busses = get_departures()
            run_vertical_scroll(busses)
            if not busses:
                time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
