"""Erase the outgoing frame and reveal the incoming frame in its owning child."""

from contextlib import contextmanager
import signal
import time

from PIL import Image, ImageChops

from display_utils import FramePacer, SWEEP_SECONDS, TRANSITION_FPS, map_serpentine, render_sweep, sweep_position


def wipe_frame(image, progress, reveal=False):
    """Apply a logical left-to-right wipe to the folded physical matrix image."""
    if image.mode != "1" or image.size != (128, 8):
        raise ValueError("Handoff needs a monochrome 128x8 physical frame")
    boundary = max(0, min(64, sweep_position(progress)))
    frame = Image.new("1", image.size, 0) if reveal else image.copy()
    if boundary:
        # The lower logical row occupies the reversed right half of the chain.
        for box in ((0, 0, boundary, 8), (128 - boundary, 0, 128, 8)):
            frame.paste(image.crop(box) if reveal else 0, box)
    return ImageChops.logical_or(frame, map_serpentine(render_sweep(progress)))


@contextmanager
def _atomic_frame():
    # On the Pi, defer TERM until the SPI write and its snapshot agree. The
    # first reveal can defer it for one sweep; erase plus reveal stay under the
    # controller's four-second graceful-stop deadline.
    mask = getattr(signal, "pthread_sigmask", None)
    previous = mask(signal.SIG_BLOCK, {signal.SIGTERM}) if mask else None
    try:
        yield
    finally:
        if mask:
            mask(signal.SIG_SETMASK, previous)


class DisplayHandoff:
    def __init__(self, device, original_display):
        self.device = device
        self.original_display = original_display
        self.last_frame = None
        self.initializing = True
        self.revealed = False
        self.stopping = False
        self.frame_depth = 0
        self.pending_stop = False

    @contextmanager
    def frame(self):
        # A background fetch thread can receive TERM even while the main thread
        # masks it. Python still runs that handler on the main thread, so defer
        # the stop explicitly until the completed frame has been recorded.
        self.frame_depth += 1
        try:
            with _atomic_frame():
                yield
        finally:
            self.frame_depth -= 1
            if not self.frame_depth and self.pending_stop:
                self.pending_stop = False
                self.stop()

    def _write(self, image):
        result = self.original_display(self.device, image)
        self.last_frame = image.copy()
        return result

    def _animate(self, image, reveal):
        target = image.copy()
        self._write(wipe_frame(target, 0.0, reveal=reveal))
        started = time.monotonic()
        pacer = FramePacer(TRANSITION_FPS)
        while True:
            pacer.wait()
            progress = min(1.0, (time.monotonic() - started) / SWEEP_SECONDS)
            result = self._write(wipe_frame(target, progress, reveal=reveal))
            if progress >= 1.0:
                return result

    def display(self, image):
        with self.frame():
            if self.stopping:
                return None
            if not self.initializing and not self.revealed and image.getbbox() is not None:
                self.revealed = True
                return self._animate(image, reveal=True)
            return self._write(image)

    def stop(self, *_):
        if self.stopping:
            return
        if self.frame_depth:
            self.pending_stop = True
            return
        self.stopping = True
        if self.last_frame is not None and self.last_frame.getbbox() is not None:
            self._animate(self.last_frame, reveal=False)
        raise SystemExit(0)


def install_handoff():
    """Install only after GO; imports and preparation never create a device."""
    from luma.led_matrix.device import max7219

    if getattr(max7219, "_garching_handoff_installed", False):
        return
    original_init, original_display = max7219.__init__, max7219.display

    def initialize(device, *args, **kwargs):
        handoff = DisplayHandoff(device, original_display)
        device._garching_handoff = handoff
        signal.signal(signal.SIGTERM, handoff.stop)
        with handoff.frame():
            try:
                original_init(device, *args, **kwargs)
            finally:
                handoff.initializing = False
            # Normal Luma cleanup must close SPI without hiding/clearing the
            # panel before the controller can take over its already-erased image.
            device.persist = True

    def display(device, image):
        handoff = getattr(device, "_garching_handoff", None)
        return handoff.display(image) if handoff is not None else original_display(device, image)

    max7219.__init__, max7219.display = initialize, display
    max7219._garching_handoff_installed = True
