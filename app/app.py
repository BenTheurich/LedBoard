import subprocess
import socket
import threading
from flask import Flask, render_template, request, redirect
from message import MAX_MESSAGE_LENGTH, validate_message

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096

# --- CONFIGURATION ---
SCRIPTS = {
    "Clock": "clock.py",
    "Game of Life": "game_of_life.py",
    "Bus Timetable": "my_bus_script3.py",
    "Weather": "weather.py",
    "Message Board": "message.py",
    "Pong": "pong_explode2.py",
    "Music Visualizer": "visualizations.py",
    "Falling Sand": "falling_sand.py",
    "Drawing Harmonograph": "harmonograph.py",
    "Acid Rain": "acid_rain.py",
    "OFF": "clear_screen.py"
}
MODE_GROUPS = {
    "Everyday": ("Clock", "Bus Timetable", "Weather"),
    "Visualizers": ("Game of Life", "Pong", "Music Visualizer", "Falling Sand",
                    "Drawing Harmonograph", "Acid Rain"),
}

current_process = None
active_script_name = "OFF" # Tracks which button should be green
last_message = ""
# Flask serves requests concurrently; display ownership must change atomically.
switch_lock = threading.Lock()

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
    from luma.core.interface.serial import spi, noop
    from luma.led_matrix.device import max7219
    from luma.core.legacy import text, textsize
    from luma.core.legacy.font import proportional, CP437_FONT
    from display_utils import FramePacer, map_serpentine

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
    # One pixel per frame at a readable speed, independent of render cost.
    pacer = FramePacer(12)
    for _ in range(2):
        for x in range(w + 128 - 64):
            device.display(map_serpentine(img.crop((x, 0, x + 64, 16))))
            pacer.wait()

# --- FLASK ROUTES ---
def kill_current_process():
    # Called while switch_lock is held by the program-switch transaction.
    global current_process
    if current_process:
        current_process.terminate()
        try:
            current_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            current_process.kill()
            current_process.wait()
        current_process = None

@app.route("/")
def index():
    return controller_page()


def controller_page(message_error=None, message_value=None):
    with switch_lock:
        selected_script = active_script_name
        saved_message = last_message
    return render_template(
        "index.html", groups=MODE_GROUPS, active_script=selected_script,
        message_value=saved_message if message_value is None else message_value,
        message_error=message_error, max_message_length=MAX_MESSAGE_LENGTH,
    )


def switch_program(script_name, extra_args=()):
    """Caller holds switch_lock so every mode has one exclusive display owner."""
    global current_process, active_script_name
    print(f"Switching to: {script_name}")
    kill_current_process()
    active_script_name = "OFF"
    subprocess.run(["python3", "clear_screen.py"])
    if script_name != "OFF":
        current_process = subprocess.Popen(["python3", SCRIPTS[script_name], *extra_args])
    active_script_name = script_name

@app.route("/run", methods=["POST"])
def run_script():
    script_name = request.form.get("script_name")
    if script_name == "Message Board":
        return redirect("/#message")
    if script_name in SCRIPTS:
        with switch_lock:
            switch_program(script_name)
    return redirect("/")


@app.route("/message", methods=["POST"])
def send_message():
    global last_message
    value = request.form.get("message", "")
    try:
        message = validate_message(value)
    except ValueError as error:
        return controller_page(message_error=str(error), message_value=value), 400
    with switch_lock:
        # One argument also preserves messages beginning with '-' for argparse.
        switch_program("Message Board", ("--message=" + message,))
        last_message = message
    return redirect("/#message")


@app.errorhandler(413)
def message_too_large(error):
    return controller_page(message_error="The request is too large. Use a shorter message."), 413

if __name__ == "__main__":
    my_ip = get_ip_address()
    try:
        show_ip_on_matrix(my_ip)
    except Exception:
        pass
    app.run(host="0.0.0.0", port=5000, debug=False)
