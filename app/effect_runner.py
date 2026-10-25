"""Run a hardware-free image generator on the folded matrix display."""
import signal
import time

from display_utils import FramePacer, map_serpentine


def run(effect):
    from luma.core.interface.serial import spi, noop
    from luma.led_matrix.device import max7219

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    device = max7219(spi(port=0, device=0, gpio=noop()), cascaded=16,
                     block_orientation=-90, rotate=0)
    device.contrast(16)
    pacer = FramePacer(20)
    previous = time.monotonic()
    elapsed = 0.0
    previous_phase = None
    print(f"Starting {type(effect).__name__}...", flush=True)
    try:
        while running:
            now = time.monotonic()
            delta = now - previous
            elapsed += delta
            previous = now
            image = effect.render(elapsed, delta)
            phase = getattr(effect, "phase", None)
            grains = getattr(effect, "grains", None)
            cycles = getattr(effect, "completed_cycles", None)
            if isinstance(phase, str) and grains is not None and cycles is not None and phase != previous_phase:
                print(f"{type(effect).__name__} phase={phase} "
                      f"grains={grains} cycles={cycles}", flush=True)
                previous_phase = phase
            if image.mode != "1" or image.size != (64, 16):
                raise ValueError("Effect must render a monochrome 64x16 image")
            device.display(map_serpentine(image))
            pacer.wait()
    finally:
        device.clear()
