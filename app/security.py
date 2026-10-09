"""Small signed-cookie session middleware using only the Python standard library."""

import base64
import binascii
import hashlib
import hmac
import json
import time
from http.cookies import SimpleCookie


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SignedSessionMiddleware:
    """Expose a small, authenticated session dict through ``request.session``."""

    def __init__(self, app, secret_key: str, max_age: int = 28800,
                 same_site: str = "strict", https_only: bool = False,
                 cookie_name: str = "leadflow_session"):
        self.app = app
        self.secret_key = secret_key.encode("utf-8")
        self.max_age = max_age
        self.same_site = same_site
        self.https_only = https_only
        self.cookie_name = cookie_name

    def _signature(self, payload: str) -> str:
        return _encode(hmac.new(self.secret_key, payload.encode("ascii"), hashlib.sha256).digest())

    def _load(self, headers) -> dict:
        cookies = SimpleCookie()
        try:
            raw = next((value.decode("latin-1") for name, value in headers if name.lower() == b"cookie"), "")
            cookies.load(raw)
            token = cookies[self.cookie_name].value
            payload, signature = token.rsplit(".", 1)
            if not hmac.compare_digest(signature, self._signature(payload)):
                return {}
            data = json.loads(_decode(payload))
            issued_at = data.pop("_issued_at", 0)
            if not isinstance(issued_at, (int, float)) or time.time() - issued_at > self.max_age or issued_at > time.time() + 60:
                return {}
            return data if isinstance(data, dict) else {}
        except (KeyError, ValueError, TypeError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
            return {}

    def _cookie_header(self, session: dict) -> bytes:
        if not session:
            value = f"{self.cookie_name}=; Path=/; Max-Age=0; HttpOnly; SameSite={self.same_site}"
        else:
            data = {**session, "_issued_at": int(time.time())}
            payload = _encode(json.dumps(data, separators=(",", ":")).encode("utf-8"))
            token = f"{payload}.{self._signature(payload)}"
            value = f"{self.cookie_name}={token}; Path=/; Max-Age={self.max_age}; HttpOnly; SameSite={self.same_site}"
        if self.https_only:
            value += "; Secure"
        return value.encode("latin-1")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        session = self._load(scope.get("headers", []))
        scope["session"] = session

        async def send_with_session(message):
            if message["type"] == "http.response.start":
                has_session_cookie = any(name.lower() == b"cookie" and self.cookie_name.encode() in value
                                         for name, value in scope.get("headers", []))
                if session or has_session_cookie:
                    headers = list(message.get("headers", []))
                    headers.append((b"set-cookie", self._cookie_header(session)))
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_session)
