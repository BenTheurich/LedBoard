"""Import a display program, then wait for the controller's SPI handoff."""

import argparse
import importlib
import os
from pathlib import Path
import runpy
import sys


def prepare_mode(filename):
    # Importing these libraries does not open SPI. Mode modules must likewise
    # reserve hardware setup for their guarded entrypoint.
    for name in ("luma.core.interface.serial", "luma.led_matrix.device", "luma.core.render", Path(filename).stem):
        importlib.import_module(name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-fd", type=int, required=True)
    parser.add_argument("--go-fd", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or Path(command[0]).name != command[0] or not command[0].endswith(".py"):
        parser.error("Choose a display script in the application directory")
    filename, *extra_args = command
    prepare_mode(filename)
    with os.fdopen(args.ready_fd, "wb", buffering=0) as ready, \
            os.fdopen(args.go_fd, "rb", buffering=0) as go:
        ready.write(b"R")
        ready.close()
        if go.read(1) != b"G":
            return 1
    sys.argv = [filename, *extra_args]
    runpy.run_path(filename, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
