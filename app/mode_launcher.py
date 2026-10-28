"""Run a display program using pipes instead of opening matrix hardware."""

import argparse
import importlib
from pathlib import Path
import runpy
import sys
from types import ModuleType

from frame_transport import FrameProducer


class _VirtualSerial:
    def __init__(self, *args, **kwargs):
        pass

    def cleanup(self):
        pass


def install_frame_producer(producer):
    """Replace hardware entrypoints before any mode imports can reach them."""
    luma = importlib.import_module("luma")
    interface = importlib.import_module("luma.core.interface")
    serial = ModuleType("luma.core.interface.serial")
    serial.spi = serial.noop = _VirtualSerial
    matrix = ModuleType("luma.led_matrix")
    matrix.__path__ = []
    device = ModuleType("luma.led_matrix.device")

    def max7219(serial_interface=None, width=8, height=8, cascaded=1, rotate=0,
                block_orientation=0, blocks_arranged_in_reverse_order=False, **kwargs):
        if ((width, height, cascaded, rotate, block_orientation) != (8, 8, 16, 0, -90)
                or blocks_arranged_in_reverse_order or kwargs):
            raise ValueError("Virtual matrix requires 16 blocks with orientation -90 and rotation 0")
        return producer

    device.max7219 = max7219
    matrix.device = device
    interface.serial = serial
    luma.led_matrix = matrix
    sys.modules.update({
        "luma.core.interface.serial": serial,
        "luma.led_matrix": matrix,
        "luma.led_matrix.device": device,
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-fd", type=int, required=True)
    parser.add_argument("--resume-fd", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if (not command or Path(command[0]).name != command[0]
            or "/" in command[0] or "\\" in command[0]
            or not command[0].endswith(".py")):
        parser.error("Choose a display script in the application directory")
    filename, *extra_args = command
    producer = FrameProducer(args.frame_fd, args.resume_fd,
                             allow_blank_first=filename == "drawing.py")
    try:
        install_frame_producer(producer)
        sys.argv = [filename, *extra_args]
        runpy.run_path(filename, run_name="__main__")
    finally:
        producer.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
