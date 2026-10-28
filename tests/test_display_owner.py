import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from display_owner import DisplayOwner
from display_transition import Phase, Transition
from frame_transport import FrameProducer
from mode_switch import ModeWorker


BLACK = bytes(128)


def pattern(multiplier, offset):
    return Image.frombytes("1", (128, 8), bytes((index * multiplier + offset) % 256 for index in range(128)))


def expected_transition(outgoing, incoming=None, *, off=False):
    transition = Transition(outgoing, off=off)
    frames = []
    while not transition.done:
        if transition.phase is Phase.LOADING and incoming is not None:
            transition.offer_frame(incoming)
        frames.append((transition.phase, transition.step, transition.image().tobytes()))
        transition.advance()
    frames.append((Phase.DONE, 0, transition.image().tobytes()))
    return frames


def changed_frames(initial, frames):
    result, previous = [], initial
    for frame in frames:
        if frame != previous:
            result.append(frame)
            previous = frame
    return result


class FrameGate:
    def __init__(self, pixels):
        self.pixels = pixels
        self.entered = threading.Event()
        self.release = threading.Event()


class RecordingOutput:
    def __init__(self, *, delay=0):
        self.events = []
        self.condition = threading.Condition()
        self.gates = []
        self.closed = threading.Event()
        self.delay = delay
        self.fail_next_display = None

    def record(self, method, value=None):
        with self.condition:
            self.events.append((method, value, threading.get_ident()))
            self.condition.notify_all()

    def factory(self):
        self.record("factory")
        return self

    def show(self):
        self.record("show")

    def contrast(self, value):
        self.record("contrast", value)

    def display(self, image):
        if self.fail_next_display is not None:
            raise self.fail_next_display
        pixels = image.tobytes()
        self.record("display", pixels)
        for gate in self.gates:
            if pixels == gate.pixels and not gate.entered.is_set():
                gate.entered.set()
                if not gate.release.wait(3):
                    raise TimeoutError("The test did not release the output gate")
        if self.delay:
            time.sleep(self.delay)

    def close(self):
        self.record("close")
        self.closed.set()

    def snapshot(self):
        with self.condition:
            return list(self.events)

    def wait_for(self, predicate):
        with self.condition:
            return self.condition.wait_for(lambda: predicate(self.events), timeout=3)


class ObservableProducer(FrameProducer):
    def __init__(self, *args):
        super().__init__(*args)
        self.sent = threading.Event()

    def _write(self, packet):
        super()._write(packet)
        self.sent.set()


class DisplayOwnerTests(unittest.TestCase):
    def setUp(self):
        self.owners = []
        self.outputs = []
        self.workers = []
        self.producers = []
        self.threads = []

    def tearDown(self):
        for output in self.outputs:
            for gate in output.gates:
                gate.release.set()
        for owner in self.owners:
            try:
                owner.close()
            except RuntimeError:
                pass  # A deliberately failed owner has already closed its output.
        for worker in self.workers:
            worker.close()
        for thread in self.threads:
            thread.join(2)
        for producer in self.producers:
            producer.cleanup()
        for thread in self.threads:
            self.assertFalse(thread.is_alive(), "A producer or ticket waiter remained blocked")

    def owner(self, *, output=None, preparation_timeout=2):
        output = output or RecordingOutput()
        self.outputs.append(output)
        owner = DisplayOwner(output.factory, frame_seconds=.0005, preparation_timeout=preparation_timeout)
        self.owners.append(owner)
        return owner, output

    def channel(self):
        read_fd, frame_fd = os.pipe()
        resume_read, resume_fd = os.pipe()
        os.set_blocking(read_fd, False)
        process = Mock()
        process.poll.return_value = None
        worker = ModeWorker(process, read_fd, resume_fd)
        producer = ObservableProducer(frame_fd, resume_read)
        self.workers.append(worker)
        self.producers.append(producer)
        return worker, producer

    def run_thread(self, action):
        done, errors = threading.Event(), []

        def run():
            try:
                action()
            except BaseException as error:
                errors.append(error)
            finally:
                done.set()

        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return done, errors

    def test_delayed_first_frame_preserves_every_pass_and_resumes_after_reveal(self):
        old, target, normal = pattern(29, 31), pattern(17, 83), pattern(47, 5)
        expected = expected_transition(old, target)
        output = RecordingOutput(delay=.0015)  # Longer than a tick: late writes must not skip columns.
        loading = FrameGate(next(pixels for phase, step, pixels in expected if (phase, step) == (Phase.LOADING, 16)))
        revealing = FrameGate(next(pixels for phase, step, pixels in expected if (phase, step) == (Phase.REVEAL, 30)))
        output.gates.extend((loading, revealing))
        owner, output = self.owner(output=output)
        owner.show_frame(old, contrast=32)
        worker, producer = self.channel()
        producer.contrast(96)
        ticket = owner.begin_switch()
        owner.attach_worker(ticket, worker)
        self.assertTrue(loading.entered.wait(3), "The owner did not reach the loading pass")
        resumed_snapshot = []

        def render():
            producer.display(target)
            resumed_snapshot.extend(output.snapshot())
            producer.display(normal)
            producer.contrast(64)

        done, errors = self.run_thread(render)
        self.assertTrue(producer.sent.wait(1))
        self.assertFalse(done.is_set(), "The first frame returned during loading")
        loading.release.set()
        self.assertTrue(revealing.entered.wait(3), "FIRST did not enter reveal at the next pass boundary")
        self.assertFalse(done.is_set(), "The producer resumed before its reveal finished")
        revealing.release.set()
        owner.wait(ticket)
        self.assertTrue(done.wait(2))
        self.assertEqual(errors, [])
        self.assertTrue(output.wait_for(lambda events: ("contrast", 64) in [(name, value) for name, value, _ in events]))
        owner.close()

        events = output.snapshot()
        displayed = [value for name, value, _ in events if name == "display"]
        expected_pixels = changed_frames(old.tobytes(), [pixels for _, _, pixels in expected])
        self.assertEqual(displayed, [BLACK, old.tobytes(), *expected_pixels, normal.tobytes()])
        self.assertEqual([value for name, value, _ in events if name == "contrast"], [16, 32, 96, 64])
        self.assertEqual([value for name, value, _ in resumed_snapshot if name == "display"][-1], target.tobytes())
        self.assertEqual([value for name, value, _ in resumed_snapshot if name == "contrast"][-1], 96)
        self.assertEqual(len({thread_id for _, _, thread_id in events}), 1)
        self.assertNotEqual(events[0][2], threading.get_ident())
        self.assertEqual([name for name, _, _ in events].count("factory"), 1)
        self.assertEqual([name for name, _, _ in events].count("show"), 1)
        self.assertEqual([name for name, _, _ in events].count("close"), 1)

    def test_off_finishes_the_erase_pass_and_leaves_black(self):
        old = pattern(29, 31)
        owner, output = self.owner()
        owner.show_frame(old, contrast=40)
        ticket = owner.begin_switch(off=True)
        owner.wait(ticket)
        displayed = [value for name, value, _ in output.snapshot() if name == "display"]
        expected = expected_transition(old, off=True)
        self.assertEqual(displayed, [BLACK, old.tobytes(), *changed_frames(old.tobytes(), [pixels for _, _, pixels in expected])])
        self.assertEqual(displayed[-1], BLACK)
        self.assertIsNone(ticket.error)

    def test_cancel_finishes_black_and_worker_close_releases_pending_first(self):
        owner, output = self.owner()
        owner.show_frame(pattern(29, 31))
        worker, producer = self.channel()
        ticket = owner.begin_switch()
        owner.attach_worker(ticket, worker)
        done, errors = self.run_thread(lambda: producer.display(pattern(17, 83)))
        self.assertTrue(producer.sent.wait(1))
        failure = RuntimeError("Switch cancelled")
        owner.cancel(ticket, failure)
        with self.assertRaisesRegex(RuntimeError, "Switch cancelled"):
            owner.wait(ticket)
        self.assertEqual([value for name, value, _ in output.snapshot() if name == "display"][-1], BLACK)
        self.assertFalse(done.is_set())
        worker.close()
        self.assertTrue(done.wait(1))
        self.assertEqual([error.code for error in errors if isinstance(error, SystemExit)], [0])
        self.assertEqual(len(errors), 1)

    def test_preparation_timeout_finishes_black_and_reports_failure(self):
        owner, output = self.owner(preparation_timeout=.01)
        owner.show_frame(pattern(29, 31))
        worker, _ = self.channel()
        ticket = owner.begin_switch()
        owner.attach_worker(ticket, worker)
        with self.assertRaisesRegex(TimeoutError, "first frame"):
            owner.wait(ticket)
        self.assertEqual([value for name, value, _ in output.snapshot() if name == "display"][-1], BLACK)

    def test_close_unblocks_a_pending_ticket_waiter(self):
        owner, output = self.owner()
        ticket = owner.begin_switch()
        entered = threading.Event()

        def wait():
            entered.set()
            owner.wait(ticket)

        done, errors = self.run_thread(wait)
        self.assertTrue(entered.wait(1))
        owner.close()
        self.assertTrue(done.wait(1))
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("closed", str(errors[0]))
        self.assertTrue(output.closed.is_set())

    def test_initialization_and_output_failures_propagate_without_blocked_waiters(self):
        failure = OSError("Cannot open output")

        def fail_factory():
            raise failure

        with self.assertRaises(RuntimeError) as caught:
            DisplayOwner(fail_factory)
        self.assertIs(caught.exception.__cause__, failure)

        owner, output = self.owner()
        write_failure = OSError("Output write failed")
        output.fail_next_display = write_failure
        ticket = owner.begin_switch()
        with self.assertRaisesRegex(OSError, "Output write failed"):
            owner.wait(ticket)
        self.assertTrue(output.closed.wait(1))
        with self.assertRaises(RuntimeError) as caught:
            owner.show_frame(pattern(17, 83))
        self.assertIs(caught.exception.__cause__, write_failure)


if __name__ == "__main__":
    unittest.main()
