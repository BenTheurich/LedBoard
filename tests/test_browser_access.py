import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from flask import Flask, request
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))
from browser_access import PasswordGate, start_browser_access


class BrowserAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "test-only-board-password"
        cls.password_hash = generate_password_hash(cls.password, method="pbkdf2:sha256:1000")
        cls.origin = "https://board.example.ts.net"
        cls.secret = "test-only-session-secret-at-least-32-characters"
        cls.cookie_name = "__Host-board-session"

    def setUp(self):
        self.app = Flask(__name__, template_folder=str(APP_ROOT / "templates"))
        self.state = []

        @self.app.route("/", methods=["GET", "POST"])
        def index():
            if request.method == "POST":
                self.state.append(request.form["message"])
            return json.dumps(self.state)

        @self.app.route("/static/test.js")
        def asset():
            return "asset"

        self.gate = PasswordGate(self.app, self.password_hash, self.origin, self.secret)
        self.client = Client(self.gate, Response)

    def get(self, path="/", **kwargs):
        return self.client.get(path, base_url=self.origin, **kwargs)

    def post(self, path, data, origin=True):
        headers = {} if origin is None else {"Origin": self.origin if origin is True else origin}
        return self.client.post(path, base_url=self.origin, headers=headers, data=data)

    def login(self):
        response = self.post("/login", {"password": self.password})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/")
        return response

    def test_anonymous_visitors_get_password_only_form_without_browser_auth_prompt(self):
        response = self.get()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/login")
        response = self.get("/login")
        self.assertEqual(response.status_code, 200)

        class Inputs(HTMLParser):
            names = []

            def handle_starttag(self, tag, attrs):
                if tag == "input":
                    self.names.append(dict(attrs).get("name"))

        fields = Inputs()
        fields.feed(response.get_data(as_text=True))
        self.assertIn("password", fields.names)
        self.assertNotIn("username", fields.names)
        self.assertNotIn("WWW-Authenticate", response.headers)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        for path in ("/static/test.js", "/missing"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.mimetype, "application/json")
                self.assertNotIn("WWW-Authenticate", response.headers)
        old_basic = {"Authorization": "Basic Ym9hcmQ6dGVzdC1vbmx5LWJvYXJkLXBhc3N3b3Jk"}
        self.assertEqual(self.get(headers=old_basic).status_code, 303)
        self.assertEqual(self.post("/", {"message": "anonymous"}).status_code, 401)
        self.assertEqual(self.state, [])

    def test_login_sets_secure_cookie_and_authenticated_actions_share_app_state(self):
        with patch("browser_access.check_password_hash", wraps=check_password_hash) as verify:
            response = self.login()
            cookie = self.client.get_cookie(self.cookie_name, domain="board.example.ts.net")
            self.assertIsNotNone(cookie)
            self.assertTrue(cookie.secure)
            self.assertTrue(cookie.http_only)
            self.assertEqual(cookie.same_site, "Lax")
            self.assertEqual(cookie.path, "/")
            self.assertEqual(cookie.max_age, 7 * 24 * 60 * 60)
            self.assertIn("HttpOnly", response.headers["Set-Cookie"])
            self.assertEqual(self.get().status_code, 200)
            self.assertEqual(self.get("/static/test.js").data, b"asset")
            response = self.post("/", {"message": "hello"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(self.app.test_client().get("/").data), ["hello"])
            self.assertEqual(verify.call_count, 1)

    def test_invalid_login_and_cross_origin_requests_do_not_change_state(self):
        response = self.post("/login", {"password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertIn(b'role="alert"', response.data)
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertEqual(self.post("/login", {"password": "p" * 5000}).status_code, 413)
        for origin in (None, "null", "https://other.example", self.origin + ".evil.example"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post("/login", {"password": self.password}, origin).status_code, 403)
        self.login()
        for origin in (None, "null", "https://other.example"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post("/", {"message": "bad"}, origin).status_code, 403)
        self.assertEqual(self.state, [])

    def test_tampered_expired_and_previous_password_sessions_are_rejected(self):
        serializer = URLSafeTimedSerializer(self.secret, salt="board-browser-login")
        version = hashlib.sha256(self.password_hash.encode()).hexdigest()
        with patch("itsdangerous.timed.TimestampSigner.get_timestamp", return_value=int(time.time()) - 7 * 24 * 60 * 60 - 10):
            expired = serializer.dumps(version)
        for token in ("not-a-session", expired, serializer.dumps("previous-password-version")):
            with self.subTest(token=token):
                self.client.set_cookie(self.cookie_name, token, domain="board.example.ts.net", secure=True)
                self.assertEqual(self.get().status_code, 303)
                self.assertEqual(self.post("/", {"message": "bad"}).status_code, 401)
        self.assertEqual(self.state, [])

    def test_missing_configuration_does_not_open_listener(self):
        with patch("browser_access.Path") as path, patch("browser_access.make_server") as make:
            path.return_value.exists.return_value = False
            self.assertIsNone(start_browser_access(self.app, "absent.json"))
            make.assert_not_called()

    def test_valid_configuration_binds_only_loopback_and_shares_wsgi_app(self):
        config = {"password_hash": self.password_hash, "public_origin": self.origin, "session_secret": self.secret}
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
        valid = {"password_hash": self.password_hash, "public_origin": self.origin, "session_secret": self.secret}
        invalid = [[], {}, {**valid, "password_hash": "plain"},
                   {**valid, "password_hash": "unknown$abcdefgh$abcdefghijklmnop"},
                   {**valid, "session_secret": "short"}, {**valid, "session_secret": None},
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
