import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import mode_switch


class ModeSwitchTests(unittest.TestCase):
    def setUp(self):
        self.owner = Mock()
        self.ticket = object()
        self.owner.begin_switch.return_value = self.ticket
        self.owner_patch = patch.object(mode_switch, "get_display_owner", return_value=self.owner)
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)

    def test_launch_starts_erase_before_stopping_old_worker_or_spawning_next(self):
        events = []
        previous = Mock()
        previous.poll.return_value = None
        previous.terminate.side_effect = lambda: events.append("terminate")
        previous.wait.side_effect = lambda timeout=None: events.append("reaped")
        previous.close.side_effect = lambda: events.append("closed")
        self.owner.begin_switch.side_effect = lambda **kwargs: events.append("erase") or self.ticket
        self.owner.attach_worker.side_effect = lambda ticket, worker: events.append("attach")
        self.owner.wait.side_effect = lambda ticket: events.append("finished")
        process = Mock()

        def spawn(arguments, **kwargs):
            events.append("spawn")
            return process

        with patch.object(mode_switch.subprocess, "Popen", side_effect=spawn):
            worker = mode_switch.launch_mode("clock.py", previous=previous)
        self.addCleanup(worker.close)

        self.assertEqual(events, ["erase", "closed", "terminate", "reaped", "spawn", "attach", "finished"])
        self.owner.begin_switch.assert_called_once_with(off=False)
        self.owner.attach_worker.assert_called_once_with(self.ticket, worker)
        self.owner.wait.assert_called_once_with(self.ticket)
        self.assertIs(worker.process, process)
        process.terminate.assert_not_called()

    def test_launch_passes_only_frame_and_resume_channels_to_worker(self):
        captured = {}
        process = Mock()

        def spawn(arguments, **kwargs):
            captured.update(arguments=arguments, kwargs=kwargs)
            frame_fd = int(arguments[arguments.index("--frame-fd") + 1])
            resume_fd = int(arguments[arguments.index("--resume-fd") + 1])
            captured["child_fds"] = (frame_fd, resume_fd)
            for descriptor in captured["child_fds"]:
                os.fstat(descriptor)
            return process

        with patch.object(mode_switch.subprocess, "Popen", side_effect=spawn):
            worker = mode_switch.launch_mode("message.py", ("--message=--hello; $(literal)",))
        self.addCleanup(worker.close)

        arguments, kwargs = captured["arguments"], captured["kwargs"]
        self.assertEqual(arguments[:2], [sys.executable, "mode_launcher.py"])
        self.assertEqual(arguments[-3:], ["--", "message.py", "--message=--hello; $(literal)"])
        self.assertEqual(set(kwargs["pass_fds"]), set(captured["child_fds"]))
        self.assertNotEqual(kwargs.get("stdout"), subprocess.PIPE)
        self.assertNotEqual(kwargs.get("stderr"), subprocess.PIPE)
        for descriptor in captured["child_fds"]:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        os.fstat(worker.read_fd)
        os.fstat(worker.resume_fd)

    def test_off_starts_erasing_before_reaping_old_worker_and_waits_for_black(self):
        events = []
        previous = Mock()
        previous.poll.return_value = None
        previous.terminate.side_effect = lambda: events.append("terminate")
        previous.wait.side_effect = lambda timeout=None: events.append("reaped")
        previous.close.side_effect = lambda: events.append("closed")
        self.owner.begin_switch.side_effect = lambda **kwargs: events.append("erase") or self.ticket
        self.owner.wait.side_effect = lambda ticket: events.append("black")

        with patch.object(mode_switch.subprocess, "Popen") as spawn:
            mode_switch.clear_display(previous=previous)

        self.assertEqual(events, ["erase", "closed", "terminate", "reaped", "black"])
        self.owner.begin_switch.assert_called_once_with(off=True)
        self.owner.wait.assert_called_once_with(self.ticket)
        self.owner.attach_worker.assert_not_called()
        spawn.assert_not_called()

    def test_failed_new_worker_is_reaped_and_owner_cancellation_finishes(self):
        process = Mock()
        process.poll.return_value = None
        failure = RuntimeError("Worker closed its frame channel")
        self.owner.wait.side_effect = [failure, None]
        attached_descriptors = []
        self.owner.attach_worker.side_effect = lambda ticket, worker: attached_descriptors.extend((worker.read_fd, worker.resume_fd))

        with patch.object(mode_switch.subprocess, "Popen", return_value=process):
            with self.assertRaises(mode_switch.ModeStartError):
                mode_switch.launch_mode("clock.py")

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)
        self.owner.cancel.assert_called_once_with(self.ticket, failure)
        self.assertEqual(self.owner.wait.call_args_list, [call(self.ticket), call(self.ticket)])
        self.assertEqual(len(attached_descriptors), 2)
        for descriptor in attached_descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_failed_spawn_closes_all_pipes_and_finishes_cancellation(self):
        descriptors = []
        real_pipe = os.pipe
        failure = OSError("Cannot start process")

        def pipe():
            pair = real_pipe()
            descriptors.extend(pair)
            return pair

        with patch.object(mode_switch.os, "pipe", side_effect=pipe), \
                patch.object(mode_switch.subprocess, "Popen", side_effect=failure):
            with self.assertRaises(mode_switch.ModeStartError):
                mode_switch.launch_mode("clock.py")

        self.owner.cancel.assert_called_once_with(self.ticket, failure)
        self.owner.wait.assert_called_once_with(self.ticket)
        self.owner.attach_worker.assert_not_called()
        self.assertEqual(len(descriptors), 4)
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_off_failure_cancels_owner_and_propagates_error(self):
        failure = OSError("Display failed")
        self.owner.wait.side_effect = [failure, None]

        with self.assertRaises((mode_switch.ModeStartError, OSError)):
            mode_switch.clear_display()

        self.owner.cancel.assert_called_once_with(self.ticket, failure)
        self.assertEqual(self.owner.wait.call_args_list, [call(self.ticket), call(self.ticket)])

    def test_owner_begin_failure_still_stops_detached_previous_worker(self):
        previous = Mock()
        previous.poll.return_value = None
        self.owner.begin_switch.side_effect = RuntimeError("Display owner stopped")

        with patch.object(mode_switch.subprocess, "Popen") as spawn:
            with self.assertRaises(mode_switch.ModeStartError):
                mode_switch.launch_mode("clock.py", previous=previous)

        self.assertEqual(previous.method_calls, [
            call.close(), call.poll(), call.terminate(), call.wait(timeout=2),
        ])
        self.owner.cancel.assert_not_called()
        spawn.assert_not_called()


class WorkerCleanupTests(unittest.TestCase):
    def test_second_pipe_failure_closes_first_pipe_pair(self):
        descriptors = os.pipe()
        with patch.object(mode_switch.os, "pipe", side_effect=[descriptors, OSError("No descriptors")]), \
                patch.object(mode_switch.subprocess, "Popen") as spawn:
            with self.assertRaises(OSError):
                mode_switch._spawn("clock.py", ())
        spawn.assert_not_called()
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_resume_releases_waiting_child_and_closes_control_channel(self):
        frame_reader, frame_writer = os.pipe()
        resume_reader, resume_writer = os.pipe()
        worker = mode_switch.ModeWorker(Mock(), frame_reader, resume_writer)
        try:
            worker.send_resume()
            self.assertEqual(os.read(resume_reader, 1), b"G")
            self.assertEqual(os.read(resume_reader, 1), b"")
            self.assertIsNone(worker.resume_fd)
        finally:
            worker.close()
            os.close(frame_writer)
            os.close(resume_reader)

    def test_stop_releases_channels_before_terminating_blocked_worker(self):
        worker = Mock()
        worker.poll.return_value = None
        mode_switch.stop_process(worker)
        self.assertEqual(worker.method_calls, [call.close(), call.poll(), call.terminate(), call.wait(timeout=2)])

    def test_stubborn_worker_is_killed_reaped_and_closed(self):
        worker = Mock()
        worker.poll.return_value = None
        worker.wait.side_effect = [subprocess.TimeoutExpired("worker", 2), 0]
        mode_switch.stop_process(worker)
        self.assertEqual(worker.method_calls, [
            call.close(), call.poll(), call.terminate(), call.wait(timeout=2), call.kill(), call.wait(),
        ])

    def test_exited_worker_is_reaped_and_channels_closed(self):
        worker = Mock()
        worker.poll.return_value = 0
        mode_switch.stop_process(worker)
        self.assertEqual(worker.method_calls, [call.close(), call.poll(), call.wait()])


if __name__ == "__main__":
    unittest.main()
