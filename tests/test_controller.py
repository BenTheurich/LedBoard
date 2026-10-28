import importlib.util
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

spec = importlib.util.spec_from_file_location(
    "garching_controller", Path(__file__).resolve().parents[1] / "app" / "app.py"
)
controller = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = controller
spec.loader.exec_module(controller)


class ObservedLock:
    """Expose the second acquire attempt without relying on thread timing."""

    def __init__(self):
        self.lock = threading.Lock()
        self.counter_lock = threading.Lock()
        self.attempts = 0
        self.second_attempt = threading.Event()

    def __enter__(self):
        with self.counter_lock:
            self.attempts += 1
            if self.attempts == 2:
                self.second_attempt.set()
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


class FakeProcess:
    def __init__(self, args):
        self.args = args
        self.alive = True

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


class ControllerTests(unittest.TestCase):
    def setUp(self):
        controller.app.config["TESTING"] = True
        controller.current_process = None
        controller.active_script_name = "OFF"
        controller.switch_lock = threading.Lock()

    def tearDown(self):
        controller.current_process = None
        controller.active_script_name = "OFF"
        controller.switch_lock = threading.Lock()

    def test_overlapping_switches_leave_only_one_live_child(self):
        observed_lock = ObservedLock()
        controller.switch_lock = observed_lock
        first_clear_entered = threading.Event()
        release_first_clear = threading.Event()
        created = []
        failures = []
        responses = []

        def clear(args):
            if not first_clear_entered.is_set():
                first_clear_entered.set()
                if not release_first_clear.wait(timeout=5):
                    raise AssertionError("The first clear was not released")

        def spawn(args):
            process = FakeProcess(args)
            created.append(process)
            return process

        def post(name):
            try:
                with controller.app.test_client() as client:
                    responses.append(client.post("/run", data={"script_name": name}).status_code)
            except BaseException as error:
                failures.append(error)

        with patch.object(controller.subprocess, "run", side_effect=clear) as clear_mock, \
                patch.object(controller.subprocess, "Popen", side_effect=spawn):
            first = threading.Thread(target=post, args=("Clock",))
            second = threading.Thread(target=post, args=("Pong",))
            first.start()
            try:
                self.assertTrue(first_clear_entered.wait(timeout=5))
                second.start()
                self.assertTrue(observed_lock.second_attempt.wait(timeout=5))
                self.assertEqual(clear_mock.call_count, 1)
                self.assertEqual(created, [])
            finally:
                release_first_clear.set()
                first.join(timeout=5)
                if second.ident is not None:
                    second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(responses, [302, 302])
        self.assertEqual(len(created), 2)
        self.assertFalse(created[0].alive)
        self.assertTrue(created[1].alive)
        self.assertIs(controller.current_process, created[1])
        self.assertEqual(controller.active_script_name, "Pong")

    def test_off_stops_child_and_clears_without_spawning(self):
        process = Mock()
        controller.current_process = process
        controller.active_script_name = "Clock"
        with patch.object(controller.subprocess, "run") as clear, \
                patch.object(controller.subprocess, "Popen") as spawn:
            response = controller.app.test_client().post("/run", data={"script_name": "OFF"})

        self.assertEqual(response.status_code, 302)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)
        clear.assert_called_once_with(["python3", "clear_screen.py"])
        spawn.assert_not_called()
        self.assertIsNone(controller.current_process)
        self.assertEqual(controller.active_script_name, "OFF")

    def test_timeout_kills_and_reaps_child_before_switching(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("old-child", 2), 0]
        controller.current_process = process
        with patch.object(controller.subprocess, "run"), \
                patch.object(controller.subprocess, "Popen"):
            response = controller.app.test_client().post("/run", data={"script_name": "OFF"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(process.method_calls, [call.terminate(), call.wait(timeout=2), call.kill(), call.wait()])
        self.assertIsNone(controller.current_process)

    def test_unknown_program_leaves_current_program_untouched(self):
        process = Mock()
        controller.current_process = process
        controller.active_script_name = "Clock"
        with patch.object(controller.subprocess, "run") as clear, \
                patch.object(controller.subprocess, "Popen") as spawn:
            response = controller.app.test_client().post("/run", data={"script_name": "Unknown"})

        self.assertEqual(response.status_code, 302)
        process.terminate.assert_not_called()
        clear.assert_not_called()
        spawn.assert_not_called()
        self.assertIs(controller.current_process, process)
        self.assertEqual(controller.active_script_name, "Clock")

    def test_selected_visuals_are_available_on_the_main_panel(self):
        expected = {"Falling Sand": "falling_sand.py", "Drawing Harmonograph": "harmonograph.py", "Acid Rain": "acid_rain.py"}
        with patch.object(controller.subprocess, "run"), patch.object(controller.subprocess, "Popen") as spawn:
            client = controller.app.test_client()
            for name, script in expected.items():
                with self.subTest(mode=name):
                    response = client.post("/run", data={"script_name": name})
                    self.assertEqual(response.status_code, 302)
                    spawn.assert_called_with(["python3", script])
                    self.assertEqual(controller.active_script_name, name)
        html = controller.app.test_client().get("/").get_data(as_text=True)
        for name in expected:
            self.assertIn(name, html)

    def test_weather_message_and_drawing_have_exclusive_display_ownership(self):
        created = []
        def spawn(args):
            process = FakeProcess(args)
            created.append(process)
            return process

        with patch.object(controller.subprocess, "run"), \
                patch.object(controller.subprocess, "Popen", side_effect=spawn):
            client = controller.app.test_client()
            self.assertEqual(client.post("/run", data={"script_name": "Weather"}).status_code, 302)
            value = "--hello; $(no command)\nSecond line"
            response = client.post("/message", data={"message": value})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(created[0].alive)
            self.assertEqual(created[1].args, ["python3", "message.py", "--message=--hello; $(no command)\nSecond line"])
            html = response.get_data(as_text=True)
            self.assertIn('value="Message Board"', html)
            self.assertEqual(controller.active_script_name, "Message Board")
            self.assert_message_field(html, value)
            pixels = "1" + "0" * 1023
            response = client.post("/drawing", data={"pixels": pixels})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, "/#drawing")
            self.assertFalse(created[1].alive)
            self.assertEqual(created[2].args, ["python3", "drawing.py", "--pixels=" + pixels])
            self.assertTrue(created[2].alive)
            self.assertEqual(controller.active_script_name, "Pixel Drawing")
            client.post("/run", data={"script_name": "Clock"})
            self.assertFalse(created[2].alive)
            self.assertTrue(created[3].alive)

    def assert_message_field(self, html, expected=""):
        class MessageField(HTMLParser):
            attrs = None
            value = ""
            inside = False

            def handle_starttag(self, tag, attrs):
                if tag == "textarea":
                    self.attrs = dict(attrs)
                    self.inside = True

            def handle_data(self, data):
                if self.inside:
                    self.value += data

            def handle_endtag(self, tag):
                if tag == "textarea":
                    self.inside = False

        field = MessageField()
        field.feed(html)
        self.assertIsNotNone(field.attrs)
        self.assertEqual(field.value, expected)
        self.assertEqual(field.attrs["placeholder"], "Type your message here")

    def test_message_field_starts_blank(self):
        self.assert_message_field(controller.app.test_client().get("/").get_data(as_text=True))

    def test_success_keeps_original_message_text_in_the_form(self):
        value = ' Grüße!\r\nCafé “12°” '
        with patch.object(controller.subprocess, "run"), patch.object(controller.subprocess, "Popen") as spawn:
            response = controller.app.test_client().post("/message", data={"message": value})
        self.assertEqual(response.status_code, 200)
        self.assert_message_field(response.get_data(as_text=True), value)
        spawn.assert_called_once_with(["python3", "message.py", '--message=Grüße!\nCafé "12°"'])

    def test_json_submissions_report_the_selected_mode(self):
        client = controller.app.test_client()
        headers = {"Accept": "application/json"}
        with patch.object(controller.subprocess, "run"), patch.object(controller.subprocess, "Popen"):
            for path, data, expected in (
                ("/message", {"message": "♥ Grüße"}, "Message Board"),
                ("/drawing", {"pixels": "0" * 1024}, "Pixel Drawing"),
            ):
                with self.subTest(path=path):
                    response = client.post(path, data=data, headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json(), {"active_script": expected})

    def test_drawing_button_opens_editor_without_starting_a_child(self):
        with patch.object(controller.subprocess, "run") as clear, \
                patch.object(controller.subprocess, "Popen") as spawn:
            response = controller.app.test_client().post("/run", data={"script_name": "Pixel Drawing"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/#drawing")
        clear.assert_not_called()
        spawn.assert_not_called()

    def test_invalid_drawing_payloads_preserve_the_current_display(self):
        process = Mock()
        controller.current_process = process
        controller.active_script_name = "Clock"
        client = controller.app.test_client()
        with patch.object(controller.subprocess, "run") as clear, \
                patch.object(controller.subprocess, "Popen") as spawn:
            for data in ({}, {"pixels": "0" * 1023}, {"pixels": "0" * 1025},
                         {"pixels": "0" * 1023 + ";"}):
                with self.subTest(data=str(data)[:50]):
                    response = client.post("/drawing", data=data, headers={"Accept": "application/json"})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("1,024 pixels", response.get_json()["error"])
        process.terminate.assert_not_called()
        clear.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(controller.active_script_name, "Clock")

    def test_invalid_messages_preserve_current_display_and_form_text(self):
        process = Mock()
        controller.current_process = process
        controller.active_script_name = "Weather"
        with patch.object(controller.subprocess, "run") as clear, \
                patch.object(controller.subprocess, "Popen") as spawn:
            for value in (" ", "one\ntwo\nthree", "a" * 281, "hello \U0001f600", "\x00bad"):
                with self.subTest(value=value):
                    response = controller.app.test_client().post("/message", data={"message": value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(b'aria-invalid="true"', response.data)
                    self.assert_message_field(response.get_data(as_text=True), value)
            response = controller.app.test_client().post("/message", data={"message": '<script>alert("x")</script>\n2\n3'})
            self.assertIn(b"&lt;script&gt;", response.data)
            self.assertNotIn(b"<script>", response.data)
        process.terminate.assert_not_called()
        clear.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(controller.active_script_name, "Weather")

    def test_invalid_json_message_returns_an_error_without_switching(self):
        with patch.object(controller.subprocess, "run") as clear, \
                patch.object(controller.subprocess, "Popen") as spawn:
            response = controller.app.test_client().post(
                "/message", data={"message": "hello 😀"}, headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot display", response.get_json()["error"])
        clear.assert_not_called()
        spawn.assert_not_called()

    def test_oversized_request_does_not_switch_display(self):
        with patch.object(controller.subprocess, "run") as clear:
            response = controller.app.test_client().post("/message", data={"message": "a" * 5000})
        self.assertEqual(response.status_code, 413)
        self.assertIn(b"Use a shorter message", response.data)
        clear.assert_not_called()


if __name__ == "__main__":
    unittest.main()
