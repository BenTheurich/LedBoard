"""Optional password-protected loopback listener for Tailscale Funnel."""

import hashlib
import hmac
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash
from werkzeug.serving import make_server
from werkzeug.utils import redirect
from werkzeug.wrappers import Request, Response

COOKIE_NAME = "__Host-board-session"
SESSION_SECONDS = 7 * 24 * 60 * 60


class PasswordGate:
    def __init__(self, app, password_hash, public_origin, session_secret):
        self.application = app.wsgi_app
        self.login_template = app.jinja_env.get_template("login.html")
        self.password_hash = password_hash
        self.public_origin = public_origin
        self.serializer = URLSafeTimedSerializer(session_secret, salt="board-browser-login")
        # Changing the configured password also invalidates existing sessions.
        self.password_version = hashlib.sha256(password_hash.encode()).hexdigest()

    def _authorized(self, request):
        token = request.cookies.get(COOKIE_NAME, "")
        if not token or len(token) > 1024:
            return False
        try:
            version = self.serializer.loads(token, max_age=SESSION_SECONDS)
        except BadData:
            return False
        return isinstance(version, str) and hmac.compare_digest(version, self.password_version)

    def _login(self, request):
        if request.method in {"GET", "HEAD"}:
            if self._authorized(request):
                return redirect("/", code=303)
            return Response(self.login_template.render(error=None), content_type="text/html; charset=utf-8")
        if request.method != "POST":
            return Response("Method not allowed.", status=405)
        if request.headers.get("Origin") != self.public_origin:
            return Response("Open the board page before signing in.", status=403)
        request.max_content_length = 4096
        try:
            password = request.form.get("password", "")
        except RequestEntityTooLarge:
            return Response("The login request is too large.", status=413)
        if not password or len(password) > 128 or not check_password_hash(self.password_hash, password):
            return Response(self.login_template.render(error="Incorrect password."), status=401,
                            content_type="text/html; charset=utf-8")
        response = redirect("/", code=303)
        response.set_cookie(COOKIE_NAME, self.serializer.dumps(self.password_version),
                            max_age=SESSION_SECONDS, secure=True, httponly=True, samesite="Lax", path="/")
        return response

    def __call__(self, environ, start_response):
        request = Request(environ)

        def public_response(status, headers, exc_info=None):
            names = {"cache-control", "x-frame-options", "x-content-type-options", "referrer-policy"}
            headers = [(name, value) for name, value in headers if name.lower() not in names]
            headers.extend([
                ("Cache-Control", "no-store"),
                ("X-Frame-Options", "DENY"),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "same-origin"),
            ])
            return start_response(status, headers, exc_info)

        if request.path == "/login":
            return self._login(request)(environ, public_response)
        if not self._authorized(request):
            response = redirect("/login", code=303) if request.path == "/" and request.method in {"GET", "HEAD"} else Response(
                json.dumps({"error": "Sign in to the board before sending a command."}), status=401,
                content_type="application/json")
            return response(environ, public_response)
        # Require the public origin in addition to the browser's session cookie.
        if request.method not in {"GET", "HEAD"} and request.headers.get("Origin") != self.public_origin:
            return Response("Open the board page before sending a command.", status=403)(environ, public_response)
        return self.application(environ, public_response)


def start_browser_access(app, config_path=None):
    """Share the existing app/state on loopback port 5001 when configured."""
    path = Path(config_path) if config_path is not None else Path.home() / ".garching-board" / "browser-access.json"
    if not path.exists():
        return None
    if path.stat().st_size > 4096:
        raise ValueError("Browser access configuration is too large")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Browser access configuration must be an object")
    password_hash, origin, session_secret = (config.get(key) for key in ("password_hash", "public_origin", "session_secret"))
    if not isinstance(session_secret, str) or not 32 <= len(session_secret) <= 128:
        raise ValueError("Browser access session secret is invalid")
    if not isinstance(password_hash, str) or not 20 <= len(password_hash) <= 2048 or len(password_hash.split("$")) != 3:
        raise ValueError("Browser access password hash is invalid")
    # Reject unsupported hash methods before binding a public-facing listener.
    check_password_hash(password_hash, "")
    if not isinstance(origin, str) or len(origin) > 512:
        raise ValueError("Browser access public origin is invalid")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.netloc != parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Browser access public origin must be an HTTPS hostname")
    gate = PasswordGate(app, password_hash, origin, session_secret)
    server = make_server("127.0.0.1", 5001, gate, threaded=True)
    threading.Thread(target=server.serve_forever, name="board-browser-access", daemon=True).start()
    return server
