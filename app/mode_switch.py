"""Switch frame workers while one persistent owner continues drawing."""
from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path
import subprocess
import sys

from display_owner import DisplayOwner

STOP_TIMEOUT = 2


class ModeStartError(RuntimeError):
    pass


@dataclass
class ModeWorker:
    process: object
    read_fd: int
    resume_fd: int
    buffer: bytearray = field(default_factory=bytearray)

    def poll(self):
        return self.process.poll()

    def terminate(self):
        return self.process.terminate()

    def wait(self, **kwargs):
        return self.process.wait(**kwargs)

    def kill(self):
        return self.process.kill()

    def send_resume(self):
        if self.resume_fd is None:
            raise RuntimeError("The worker was already resumed or closed")
        descriptor, self.resume_fd = self.resume_fd, None
        try:
            os.write(descriptor, b"G")
        finally:
            os.close(descriptor)

    def close(self):
        for name in ("read_fd", "resume_fd"):
            descriptor = getattr(self, name)
            setattr(self, name, None)
            if descriptor is not None:
                os.close(descriptor)


@lru_cache(maxsize=1)
def get_display_owner():
    return DisplayOwner()


def shutdown_display():
    if get_display_owner.cache_info().currsize:
        get_display_owner().close()
        get_display_owner.cache_clear()


def stop_process(process, timeout=STOP_TIMEOUT):
    # The owner has detached this channel. EOF releases a producer waiting for
    # its first-frame acknowledgement; closing the reader releases full writes.
    process.close()
    if process.poll() is not None:
        process.wait()
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print("Mode stop timed out; killing the child", flush=True)
        process.kill()
        process.wait()


def _spawn(filename, extra_args):
    if Path(filename).name != filename or not filename.endswith(".py"):
        raise ValueError("Choose a display script in the application directory")
    read_fd, frame_fd = os.pipe()
    try:
        resume_read, resume_fd = os.pipe()
    except BaseException:
        os.close(read_fd)
        os.close(frame_fd)
        raise
    try:
        os.set_blocking(read_fd, False)
        process = subprocess.Popen(
            [sys.executable, "mode_launcher.py", "--frame-fd", str(frame_fd),
             "--resume-fd", str(resume_read), "--", filename, *extra_args],
            pass_fds=(frame_fd, resume_read),
        )
        return ModeWorker(process, read_fd, resume_fd)
    except BaseException:
        os.close(read_fd)
        os.close(resume_fd)
        raise
    finally:
        os.close(frame_fd)
        os.close(resume_read)


def _switch(filename, extra_args=(), previous=None):
    worker = None
    try:
        owner = get_display_owner()
        ticket = owner.begin_switch(off=filename is None)
    except Exception:
        if previous is not None:
            stop_process(previous)
        raise
    try:
        if previous is not None:
            stop_process(previous)
        if filename is not None:
            worker = _spawn(filename, extra_args)
            owner.attach_worker(ticket, worker)
        owner.wait(ticket)
        return worker
    except Exception as error:
        try:
            owner.cancel(ticket, error)
        finally:
            if worker is not None:
                stop_process(worker)
        try:
            owner.wait(ticket)
        except Exception:
            pass
        raise


def launch_mode(filename, extra_args=(), previous=None):
    try:
        return _switch(filename, extra_args, previous)
    except Exception as error:
        raise ModeStartError(f"Could not start {filename}. Try selecting the mode again.") from error


def clear_display(previous=None):
    try:
        _switch(None, previous=previous)
    except Exception as error:
        raise ModeStartError("Could not clear the board. Try again.") from error
