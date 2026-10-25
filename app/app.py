import subprocess
import socket
import time
from flask import Flask, render_template, request, redirect
from luma.core.interface.serial import spi, noop
from luma.led_matrix.device import max7219
from luma.core.render import canvas
from luma.core.legacy import text, textsize
from luma.core.legacy.font import proportional, CP437_FONT

app = Flask(__name__)

# --- CONFIGURATION ---
SCRIPTS = {
    "Clock": "clock.py",
    "Game of Life": "game_of_life.py",
    "Bus Timetable": "my_bus_script3.py",
    "Pong": "pong_explode2.py",
    "Music Visualizer": "visualizations.py",
    "OFF": "clear_screen.py"
}

current_process = None
active_script_name = "OFF" # Tracks which button should be green

# --- IP ADDRESS HELPERS ---
def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "No WiFi"
    finally:
        s.close()
    return ip

def show_ip_on_matrix(ip_addr):
    # (Hardware setup hidden to save space - exact same as before)
    serial = spi(port=0, device=0, gpio=noop())
    device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)
    device.contrast(32)
    msg = f"IP: {ip_addr}:5000"
    font = proportional(CP437_FONT)
    w, h = textsize(msg, font)
    from PIL import Image, ImageDraw
    img = Image.new("1", (w + 128, 16), 0)
    draw = ImageDraw.Draw(img)
    text(draw, (64, 4), msg, fill="white", font=font)
    for _ in range(2):
        for x in range(w + 128 - 64):
            with canvas(device) as device_draw:
                for i in range(64):
                    for j in range(16):
                        if img.getpixel((x + i, j)) > 0:
                            phys_x = i; phys_y = j
                            if j >= 8: phys_x = 64 + (63 - i); phys_y = 7 - (j - 8)
                            if phys_x < 128: device_draw.point((phys_x, phys_y), fill="white")
            time.sleep(0.02)

# --- FLASK ROUTES ---
def kill_current_process():
    global current_process
    if current_process:
        current_process.terminate()
        try:
            current_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            current_process.kill()
        current_process = None

@app.route("/")
def index():
    # Pass the active_script_name to the HTML
    return render_template("index.html", scripts=SCRIPTS, active_script=active_script_name)

@app.route("/run", methods=["POST"])
def run_script():
    global current_process, active_script_name
    
    script_name = request.form.get("script_name")
    filename = SCRIPTS.get(script_name)

    if filename:
        print(f"Switching to: {script_name}")
        kill_current_process()
        subprocess.run(["python3", "clear_screen.py"])
        
        # Update the active tracker
        active_script_name = script_name
        
        if script_name != "OFF":
            current_process = subprocess.Popen(["python3", filename])
            
    return redirect("/")

if __name__ == "__main__":
    my_ip = get_ip_address()
    try:
        show_ip_on_matrix(my_ip)
    except Exception:
        pass
    app.run(host="0.0.0.0", port=5000, debug=False)
