"""Animate mode handoff while a child prepares without touching SPI."""

from functools import lru_cache
from contextlib import contextmanager
import math
import os
import subprocess
import time

from PIL import Image, ImageDraw

from display_utils import FramePacer, map_serpentine

SWEEP_SECONDS = 0.45
TRANSITION_FPS = 40


class ModeStartError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_matrix_device():
    from luma.core.interface.serial import spi, noop
    from luma.led_matrix.device import max7219

    device = max7219(spi(port=0, device=0, gpio=noop()), cascaded=16,
                     block_orientation=-90, rotate=0)
    device.contrast(16)
    return device


def render_reset(elapsed):
    """A narrow reset sweep with dithered edges, without a full-panel flash."""
    image = Image.new("1", (64, 16), 0)
    draw = ImageDraw.Draw(image)
    x = math.floor((elapsed % SWEEP_SECONDS) / SWEEP_SECONDS * 72) - 4
    draw.rectangle((x, 0, x + 2, 15), fill=1)
    for y in range(16):
        if 0 <= x - 1 < 64 and y % 2 == 0:
            draw.point((x - 1, y), fill=1)
        if 0 <= x + 3 < 64 and y % 2:
            draw.point((x + 3, y), fill=1)
    return image


def animate_reset(ready=None, duration=SWEEP_SECONDS, timeout=15):
    """Finish a sweep after readiness; never hand SPI to an unprepared child."""
    device = get_matrix_device()
    device.contrast(16)
    started = time.monotonic()
    pacer = FramePacer(TRANSITION_FPS)
    finish_at = None
    try:
        while True:
            elapsed = time.monotonic() - started
            prepared = ready is None or ready()
            if prepared and finish_at is None:
                finish_at = max(duration, math.ceil(elapsed / SWEEP_SECONDS) * SWEEP_SECONDS)
            if finish_at is not None and elapsed >= finish_at:
                return
            if elapsed >= timeout:
                raise TimeoutError("The next mode did not become ready")
            device.display(map_serpentine(render_reset(elapsed)))
            pacer.wait()
    finally:
        device.clear()


def stop_process(process, timeout=2):
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@contextmanager
def _pipe():
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
        yield reader, writer


def launch_mode(filename, extra_args=()):
    """Prepare in parallel with animation, then grant exclusive display access."""
    process = None
    with _pipe() as (ready_read, ready_write), _pipe() as (go_read, go_write):
        try:
            process = subprocess.Popen(
                ["python3", "mode_launcher.py", "--ready-fd", str(ready_write.fileno()),
                 "--go-fd", str(go_read.fileno()), "--", filename, *extra_args],
                pass_fds=(ready_write.fileno(), go_read.fileno()),
            )
            ready_write.close()
            go_read.close()
            os.set_blocking(ready_read.fileno(), False)
            prepared = False

            def ready():
                nonlocal prepared
                if process.poll() is not None:
                    raise RuntimeError("The next mode exited during preparation")
                if not prepared:
                    try:
                        value = os.read(ready_read.fileno(), 1)
                    except BlockingIOError:
                        return False
                    if value != b"R":
                        raise RuntimeError("The next mode closed its readiness channel")
                    prepared = True
                return prepared

            animate_reset(ready)
            # animate_reset has stopped all controller writes before this grant.
            go_write.write(b"G")
            return process
        except BaseException as error:
            if process is not None:
                stop_process(process)
            # A failed spawn never reached the animation. Clear any old frame
            # only after the child is gone, without hiding the startup error.
            try:
                get_matrix_device().clear()
            except Exception:
                pass
            if isinstance(error, Exception):
                raise ModeStartError(f"Could not start {filename}. Try selecting the mode again.") from error
            raise
