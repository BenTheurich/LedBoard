"""Optional password-protected loopback listener for Tailscale Funnel."""

import hashlib
import hmac
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from werkzeug.security import check_password_hash
from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response


class PasswordGate:
    def __init__(self, application, username, password_hash, public_origin):
        self.application = application
        self.username = username.encode("utf-8")
        self.password_hash = password_hash
        self.public_origin = public_origin
        self._authorized_digest = None

    def _authorized(self, request):
        header = request.headers.get("Authorization", "")
        if len(header) > 2048:
            return False
        digest = hashlib.sha256(header.encode("utf-8")).digest()
        if self._authorized_digest is not None and hmac.compare_digest(digest, self._authorized_digest):
            return True
        credentials = request.authorization
        if credentials is None or credentials.type != "basic":
            return False
        username = credentials.username or ""
        password = credentials.password or ""
        if len(username) > 128 or len(password) > 128:
            return False
        if not hmac.compare_digest(username.encode("utf-8"), self.username):
            return False
        if not check_password_hash(self.password_hash, password):
            return False
        # All visitors share one credential. Cache only its digest so each asset
        # request does not repeat an expensive password derivation on the Pi Zero.
        self._authorized_digest = digest
        return True

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

        if not self._authorized(request):
            response = Response("Enter the board username and password.", status=401,
                                content_type="text/plain; charset=utf-8")
            response.headers["WWW-Authenticate"] = 'Basic realm="Garching Board", charset="UTF-8"'
            return response(environ, public_response)
        # Browsers automatically reuse Basic credentials. Require the public
        # origin on mutations so a different website cannot submit board actions.
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
    username, password_hash, origin = (config.get(key) for key in ("username", "password_hash", "public_origin"))
    if not isinstance(username, str) or not 1 <= len(username) <= 128 or ":" in username or not username.isprintable():
        raise ValueError("Browser access username is invalid")
    if not isinstance(password_hash, str) or not 20 <= len(password_hash) <= 2048 or len(password_hash.split("$")) != 3:
        raise ValueError("Browser access password hash is invalid")
    # Reject unsupported hash methods before binding a public-facing listener.
    check_password_hash(password_hash, "")
    if not isinstance(origin, str) or len(origin) > 512:
        raise ValueError("Browser access public origin is invalid")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.netloc != parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Browser access public origin must be an HTTPS hostname")
    gate = PasswordGate(app.wsgi_app, username, password_hash, origin)
    server = make_server("127.0.0.1", 5001, gate, threaded=True)
    threading.Thread(target=server.serve_forever, name="board-browser-access", daemon=True).start()
    return server
