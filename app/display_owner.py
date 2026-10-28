"""One hardware owner and one uninterrupted clock for transition passes."""
from dataclasses import dataclass, field
import os
import queue
import threading
import time

from PIL import Image

from display_transition import FRAME_SECONDS, SWEEP_SECONDS, Transition
from frame_transport import FIRST, decode_frames
from matrix_output import create_matrix_output


@dataclass
class SwitchTicket:
    done: threading.Event = field(default_factory=threading.Event)
    error: Exception | None = None


@dataclass
class _Call:
    operation: str
    args: tuple
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: Exception | None = None


class DisplayOwner:
    """Only this thread calls device methods; workers supply physical bitmaps."""

    def __init__(self, output_factory=create_matrix_output, *,
                 frame_seconds=FRAME_SECONDS, preparation_timeout=20):
        self._factory = output_factory
        self._period = frame_seconds
        self._preparation_timeout = preparation_timeout
        self._calls = queue.Queue()
        self._wake = threading.Event()
        self._started = threading.Event()
        self._fatal = None
        self._stopping = False
        self._worker = None
        self._ticket = None
        self._transition = None
        self._last_image = Image.new("1", (128, 8))
        self._contrast = self._next_contrast = 16
        self._deadline = self._next_tick = None
        self._first_tick = True
        self._thread = threading.Thread(target=self._run, name="board-display", daemon=True)
        self._thread.start()
        if not self._started.wait(30):
            raise RuntimeError("The display did not initialize")
        self._check_alive()

    def _check_alive(self):
        if self._fatal is not None:
            raise RuntimeError("The display owner stopped") from self._fatal
        if not self._thread.is_alive():
            raise RuntimeError("The display owner is closed")

    def _call(self, operation, *args):
        self._check_alive()
        call = _Call(operation, args)
        self._calls.put(call)
        self._wake.set()
        while not call.done.wait(0.1):
            self._check_alive()
        if call.error:
            raise call.error
        return call.result

    def begin_switch(self, *, off=False):
        return self._call("begin", off)

    def attach_worker(self, ticket, worker):
        self._call("attach", ticket, worker)

    def cancel(self, ticket, error):
        self._call("cancel", ticket, error)

    def wait(self, ticket):
        if not ticket.done.wait(self._preparation_timeout + 4 * SWEEP_SECONDS + 5):
            self._check_alive()
            raise TimeoutError("The display transition did not finish")
        if ticket.error:
            raise ticket.error

    def show_frame(self, image, *, contrast=16):
        self._call("show", image.copy(), contrast)

    def close(self):
        if self._thread.is_alive():
            self._call("close")
            self._thread.join(5)

    def _commands(self):
        while True:
            try:
                call = self._calls.get_nowait()
            except queue.Empty:
                return
            try:
                if call.operation == "begin":
                    if self._ticket is not None:
                        raise RuntimeError("A display transition is already running")
                    self._worker = None
                    self._transition = Transition(self._last_image, off=call.args[0])
                    self._ticket = SwitchTicket()
                    self._next_tick = time.monotonic()
                    self._first_tick = True
                    self._deadline = None
                    self._next_contrast = self._contrast
                    call.result = self._ticket
                elif call.operation == "attach":
                    ticket, worker = call.args
                    if ticket is not self._ticket:
                        raise RuntimeError("The display transition was superseded")
                    self._worker = worker
                    self._deadline = time.monotonic() + self._preparation_timeout
                elif call.operation == "cancel":
                    ticket, error = call.args
                    if ticket is self._ticket:
                        ticket.error = error
                        self._transition.cancel()
                        self._worker = None
                        self._deadline = None
                elif call.operation == "show":
                    if self._ticket is not None or self._worker is not None:
                        raise RuntimeError("Startup frames cannot interrupt a selected mode")
                    self._display(*call.args)
                elif call.operation == "close":
                    self._stopping = True
                else:
                    raise ValueError("Unknown display command")
            except Exception as error:
                call.error = error
            finally:
                call.done.set()

    def _display(self, image, contrast):
        if image.mode != "1" or image.size != (128, 8):
            raise ValueError("The display needs a monochrome 128x8 image")
        if not isinstance(contrast, int) or not 0 <= contrast <= 255:
            raise ValueError("Brightness must be between 0 and 255")
        if self._contrast != contrast:
            self._output.contrast(contrast)
            self._contrast = contrast
        if self._last_image.tobytes() != image.tobytes():
            self._output.display(image)
            self._last_image = image.copy()

    def _failed_worker(self, error):
        self._worker = None
        self._deadline = None
        if self._ticket is not None:
            self._ticket.error = error
            self._transition.cancel()

    def _receive(self):
        worker = self._worker
        if worker is None:
            return
        try:
            # One bounded read keeps a noisy producer from starving the clock.
            try:
                data = os.read(worker.read_fd, 4096)
            except BlockingIOError:
                data = None
            if data == b"":
                raise RuntimeError("The mode closed its frame channel")
            if data:
                worker.buffer.extend(data)
                for kind, contrast, image in decode_frames(worker.buffer):
                    if self._transition is not None:
                        if kind == FIRST:
                            self._transition.offer_frame(image)
                            self._next_contrast = contrast
                            self._deadline = None
                    else:
                        self._display(image, contrast)
            if worker.poll() is not None:
                raise RuntimeError("The mode exited")
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            self._failed_worker(error)

    def _tick(self, now):
        if self._transition is None or now < self._next_tick:
            return
        if self._deadline is not None and now >= self._deadline:
            self._failed_worker(TimeoutError("The next mode did not supply its first frame"))
        if not self._first_tick:
            self._transition.advance()
        self._first_tick = False
        # Brightness stays fixed throughout all passes. Restore the incoming
        # mode's brightness only after its reveal completes.
        self._display(self._transition.image(), self._contrast)
        if self._transition.done:
            ticket = self._ticket
            if ticket.error is None and self._worker is not None:
                self._display(self._transition.image(), self._next_contrast)
                try:
                    self._worker.send_resume()
                except (OSError, RuntimeError) as error:
                    ticket.error = error
                    self._worker = None
                    self._display(Image.new("1", (128, 8)), self._contrast)
            self._transition = self._ticket = self._next_tick = None
            ticket.done.set()
        else:
            # Carry the deadline through phase boundaries. An overrun extends
            # the pass instead of skipping columns or catching up in a burst.
            scheduled = self._next_tick + self._period
            completed = time.monotonic()
            self._next_tick = scheduled if scheduled > completed else completed + self._period

    def _run(self):
        self._output = None
        try:
            self._output = self._factory()
            self._output.show()
            self._output.contrast(self._contrast)
            self._output.display(self._last_image)
            self._started.set()
            while not self._stopping:
                self._commands()
                if self._stopping:
                    break
                self._receive()
                self._tick(time.monotonic())
                if self._transition is not None:
                    delay = min(0.005, max(0, self._next_tick - time.monotonic()))
                else:
                    delay = 0.005 if self._worker is not None else None
                self._wake.wait(delay)
                self._wake.clear()
        except Exception as error:
            self._fatal = error
        finally:
            self._started.set()
            if self._ticket is not None:
                self._ticket.error = self._fatal or RuntimeError("The display owner closed")
                self._ticket.done.set()
            while not self._calls.empty():
                call = self._calls.get_nowait()
                call.error = self._fatal or RuntimeError("The display owner closed")
                call.done.set()
            if self._output is not None:
                self._output.close()
