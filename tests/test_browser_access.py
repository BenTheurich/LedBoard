import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from flask import Flask, request
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from browser_access import PasswordGate, start_browser_access


class BrowserAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash("test-only-board-password", method="pbkdf2:sha256:1000")
        encoded = base64.b64encode(b"board:test-only-board-password").decode("ascii")
        cls.headers = {"Authorization": "Basic " + encoded}
        cls.origin = "https://board.example.ts.net"

    def setUp(self):
        self.app = Flask(__name__)
        self.state = []

        @self.app.route("/", methods=["GET", "POST"])
        def index():
            if request.method == "POST":
                self.state.append(request.form["message"])
            return json.dumps(self.state)

        @self.app.route("/static/test.js")
        def asset():
            return "asset"

        self.gate = PasswordGate(self.app.wsgi_app, "board", self.password_hash, self.origin)
        self.client = Client(self.gate, Response)

    def test_all_paths_require_valid_credentials_and_public_headers(self):
        for path in ("/", "/static/test.js", "/missing"):
            for headers in ({}, {"Authorization": "Basic broken"}, {"Authorization": "Bearer abc"},
                            {"Authorization": "Basic " + base64.b64encode(b"board:wrong").decode()}):
                with self.subTest(path=path, headers=headers):
                    response = self.client.get(path, headers=headers)
                    self.assertEqual(response.status_code, 401)
                    self.assertIn("Basic", response.headers["WWW-Authenticate"])
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        response = self.client.get("/static/test.js", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"asset")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_authenticated_mutations_share_state_and_require_exact_origin(self):
        for origin in (None, "null", "https://other.example", self.origin + ".evil.example"):
            headers = dict(self.headers)
            if origin is not None:
                headers["Origin"] = origin
            self.assertEqual(self.client.post("/", headers=headers, data={"message": "bad"}).status_code, 403)
        self.assertEqual(self.state, [])
        response = self.client.post("/", headers={**self.headers, "Origin": self.origin}, data={"message": "hello"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(self.app.test_client().get("/").data), ["hello"])
        self.assertEqual(self.state, ["hello"])
        self.assertEqual(json.loads(self.client.get("/", headers=self.headers).data), ["hello"])

    def test_only_successful_authentication_is_cached(self):
        with patch("browser_access.check_password_hash", wraps=check_password_hash) as verify:
            self.assertEqual(self.client.get("/", headers=self.headers).status_code, 200)
            self.assertEqual(self.client.get("/", headers=self.headers).status_code, 200)
            self.assertEqual(verify.call_count, 1)
            wrong = {"Authorization": "Basic " + base64.b64encode(b"board:wrong").decode()}
            self.assertEqual(self.client.get("/", headers=wrong).status_code, 401)
            self.assertEqual(self.client.get("/", headers=wrong).status_code, 401)
            self.assertEqual(verify.call_count, 3)

    def test_missing_configuration_does_not_open_listener(self):
        with patch("browser_access.Path") as path, patch("browser_access.make_server") as make:
            path.return_value.exists.return_value = False
            self.assertIsNone(start_browser_access(self.app, "absent.json"))
            make.assert_not_called()

    def test_valid_configuration_binds_only_loopback_and_shares_wsgi_app(self):
        config = {"username": "board", "password_hash": self.password_hash, "public_origin": self.origin}
        with patch("browser_access.Path") as path, patch("browser_access.make_server") as make, patch("browser_access.threading.Thread") as thread:
            path.return_value.stat.return_value.st_size = 100
            path.return_value.read_text.return_value = json.dumps(config)
            server = start_browser_access(self.app, "access.json")
            self.assertIs(server, make.return_value)
            args, kwargs = make.call_args
            self.assertEqual(args[:2], ("127.0.0.1", 5001))
            self.assertEqual(args[2].application, self.app.wsgi_app)
            self.assertEqual(kwargs, {"threaded": True})
            self.assertTrue(thread.call_args.kwargs["daemon"])
            thread.return_value.start.assert_called_once_with()

    def test_invalid_configuration_never_opens_listener(self):
        valid = {"username": "board", "password_hash": self.password_hash, "public_origin": self.origin}
        invalid = [[], {}, {**valid, "username": "a:b"}, {**valid, "password_hash": "plain"},
                   {**valid, "password_hash": "unknown$abcdefgh$abcdefghijklmnop"},
                   *({**valid, "public_origin": origin} for origin in (
                       "http://board.example", "https://board.example/", "https://user@board.example",
                       "https://board.example:443", "https://board.example/path", "https://board.example?q=1"))]
        with patch("browser_access.Path") as path, patch("browser_access.make_server") as make:
            path.return_value.stat.return_value.st_size = 100
            for config in invalid:
                with self.subTest(config=config):
                    path.return_value.read_text.return_value = json.dumps(config)
                    with self.assertRaises(ValueError):
                        start_browser_access(self.app, "access.json")
            path.return_value.stat.return_value.st_size = 4097
            with self.assertRaises(ValueError):
                start_browser_access(self.app, "access.json")
            make.assert_not_called()


if __name__ == "__main__":
    unittest.main()
