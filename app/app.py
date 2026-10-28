import socket
import threading
from flask import Flask, jsonify, render_template, request, redirect
from message import MAX_MESSAGE_LENGTH, validate_message
from drawing import WIDTH, HEIGHT, validate_pixels
from mode_switch import ModeStartError, animate_reset, get_matrix_device, launch_mode, stop_process

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096

# --- CONFIGURATION ---
SCRIPTS = {
    "Clock": "clock.py",
    "Game of Life": "game_of_life.py",
    "Bus Timetable": "my_bus_script3.py",
    "Weather": "weather.py",
    "Message Board": "message.py",
    "Pixel Drawing": "drawing.py",
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
    from luma.core.legacy import text, textsize
    from luma.core.legacy.font import proportional, CP437_FONT
    from display_utils import FramePacer, map_serpentine

    device = get_matrix_device()
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
        stop_process(current_process)
        current_process = None

@app.route("/")
def index():
    return controller_page()


def controller_page(message_error=None, message_value="", drawing_error=None):
    with switch_lock:
        selected_script = active_script_name
    return render_template(
        "index.html", groups=MODE_GROUPS, active_script=selected_script,
        message_value=message_value,
        message_error=message_error, max_message_length=MAX_MESSAGE_LENGTH,
        drawing_error=drawing_error,
        drawing_width=WIDTH, drawing_height=HEIGHT,
    )


def switch_program(script_name, extra_args=()):
    """Caller holds switch_lock so every mode has one exclusive display owner."""
    global current_process, active_script_name
    print(f"Switching to: {script_name}", flush=True)
    kill_current_process()
    active_script_name = "OFF"
    if script_name == "OFF":
        try:
            animate_reset()
        except Exception as error:
            raise ModeStartError("Could not clear the board. Try again.") from error
    else:
        try:
            current_process = launch_mode(SCRIPTS[script_name], extra_args)
        except ModeStartError as error:
            raise ModeStartError(f"Could not start {script_name}. Try again.") from error
    active_script_name = script_name

@app.route("/run", methods=["POST"])
def run_script():
    script_name = request.form.get("script_name")
    if script_name == "Message Board":
        return redirect("/#message")
    if script_name == "Pixel Drawing":
        return redirect("/#drawing")
    if script_name in SCRIPTS:
        with switch_lock:
            switch_program(script_name)
            selected_script = active_script_name
    else:
        with switch_lock:
            selected_script = active_script_name
    if request.accept_mimetypes.best == "application/json":
        return jsonify(active_script=selected_script)
    return redirect("/")


@app.errorhandler(ModeStartError)
def mode_start_failed(error):
    if request.accept_mimetypes.best == "application/json":
        with switch_lock:
            selected_script = active_script_name
        return jsonify(error=str(error), active_script=selected_script), 500
    return str(error), 500


@app.route("/message", methods=["POST"])
def send_message():
    value = request.form.get("message", "")
    try:
        message = validate_message(value)
    except ValueError as error:
        if request.accept_mimetypes.best == "application/json":
            return jsonify(error=str(error)), 400
        return controller_page(message_error=str(error), message_value=value), 400
    with switch_lock:
        # One argument also preserves messages beginning with '-' for argparse.
        switch_program("Message Board", ("--message=" + message,))
    if request.accept_mimetypes.best == "application/json":
        return jsonify(active_script="Message Board")
    return controller_page(message_value=value)


@app.route("/drawing", methods=["POST"])
def send_drawing():
    try:
        pixels = validate_pixels(request.form.get("pixels", ""))
    except ValueError as error:
        if request.accept_mimetypes.best == "application/json":
            return jsonify(error=str(error)), 400
        return controller_page(drawing_error=str(error)), 400
    with switch_lock:
        switch_program("Pixel Drawing", ("--pixels=" + pixels,))
    if request.accept_mimetypes.best == "application/json":
        return jsonify(active_script="Pixel Drawing")
    return redirect("/#drawing")


@app.errorhandler(413)
def message_too_large(error):
    if request.accept_mimetypes.best == "application/json":
        return jsonify(error="The request is too large. Use a shorter message."), 413
    return controller_page(message_error="The request is too large. Use a shorter message."), 413

if __name__ == "__main__":
    my_ip = get_ip_address()
    try:
        show_ip_on_matrix(my_ip)
    except Exception:
        pass
    from browser_access import start_browser_access
    browser_server = start_browser_access(app)
    try:
        app.run(host="0.0.0.0", port=5000, debug=False)
    finally:
        if browser_server is not None:
            browser_server.shutdown()
            browser_server.server_close()
