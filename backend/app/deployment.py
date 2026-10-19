"""Optional shared-password access to a single-origin hosted demonstration."""

import asyncio
import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from urllib.parse import parse_qs

from starlette.requests import HTTPConnection
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings

COOKIE_NAME = "veyra_demo_session"
SESSION_SECONDS = 12 * 60 * 60

LOGIN_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Вход · Veyra</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b1017;color:#e9edf5;
font:16px/1.6 system-ui,sans-serif;min-height:100vh;display:grid;place-items:center;padding:24px}
main{width:min(100%,410px);padding:38px;border:1px solid #253141;border-radius:22px;
background:#121b27;box-shadow:0 24px 70px #0004}.brand{font-size:14px;font-weight:700;
letter-spacing:.2em;color:#83cab6}h1{font-size:28px;line-height:1.25;margin:22px 0 12px}
p{color:#a6b3c4;margin:0 0 24px}label{font-size:14px;display:block;margin-bottom:9px}
input,button{width:100%;font:inherit;border-radius:10px;padding:12px 14px}
input{background:#0b121c;color:#fff;border:1px solid #42526a;outline:none}
input:focus{border-color:#83cab6;box-shadow:0 0 0 3px #83cab622}
button{margin-top:18px;border:0;background:#99dcc6;color:#10241d;font-weight:650;cursor:pointer}
button:hover{background:#b6ead9}.error{color:#ffb7b7;font-size:14px;margin:12px 0 0}
footer{font-size:12px;color:#748397;margin-top:26px}
</style></head><body><main><div class="brand">VEYRA</div>
<h1>Голосовой AI-ассистент</h1><p>Введите пароль доступа, чтобы открыть демонстрацию.</p>
<form method="post" action="/login"><label for="password">Пароль доступа</label>
<input id="password" name="password" type="password" required autofocus
autocomplete="current-password" maxlength="512"><button type="submit">Войти в Veyra</button>
<!--ERROR--></form><footer>Демонстрационная платформа · RU / KZ</footer></main></body></html>"""


class DemoAccessMiddleware:
    """One small ASGI gate covers static files, APIs and WebSocket handshakes."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        if settings.demo_access_password is None or settings.demo_session_secret is None:
            raise RuntimeError("Set both DEMO_ACCESS_PASSWORD and DEMO_SESSION_SECRET")
        self.app = app
        self.password = settings.demo_access_password.get_secret_value().encode("utf-8")
        secret = settings.demo_session_secret.get_secret_value().encode("utf-8")
        if len(self.password) < 16 or len(secret) < 32:
            raise RuntimeError(
                "Demo password must be at least 16 bytes; session secret at least 32"
            )
        self.signing_key = hmac.digest(secret, self.password, "sha256")
        self.origin = settings.frontend_origin.rstrip("/")
        self.attempts: OrderedDict[str, list[float]] = OrderedDict()

    def issue_cookie(self) -> str:
        payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_urlsafe(16)}"
        signature = hmac.new(self.signing_key, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def authenticated(self, connection: HTTPConnection) -> bool:
        cookie = connection.cookies.get(COOKIE_NAME, "")
        if not cookie or len(cookie) > 256:
            return False
        try:
            expiry_text, nonce, signature = cookie.split(".")
            if len(signature) != 64 or any(char not in "0123456789abcdef" for char in signature):
                return False
            expiry = int(expiry_text)
            now = int(time.time())
            if not now < expiry <= now + SESSION_SECONDS or not nonce:
                return False
            payload = f"{expiry_text}.{nonce}".encode()
            expected = hmac.new(self.signing_key, payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature, expected)
        except (TypeError, ValueError, UnicodeError):
            return False

    @staticmethod
    def error(code: str, message: str, status: int) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": code, "message": message}},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    def login_page(message: str = "", status: int = 200) -> HTMLResponse:
        # Only application-owned messages are inserted, never a submitted value.
        error = f'<p class="error" role="alert">{message}</p>' if message else ""
        return HTMLResponse(
            LOGIN_HTML.replace("<!--ERROR-->", error),
            status_code=status,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                    "frame-ancestors 'none'; base-uri 'none'"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    def rate_allowed(self, scope: Scope) -> bool:
        now = time.monotonic()
        address = (scope.get("client") or ("unknown", 0))[0]
        recent = [stamp for stamp in self.attempts.pop(address, []) if now - stamp < 60]
        allowed = len(recent) < 10
        if allowed:
            recent.append(now)
        self.attempts[address] = recent
        if len(self.attempts) > 512:
            self.attempts.popitem(last=False)
        return allowed

    async def login(self, scope: Scope, receive: Receive) -> Response:
        if not self.rate_allowed(scope):
            response = self.login_page("Слишком много попыток. Подождите минуту.", 429)
            response.headers["Retry-After"] = "60"
            return response
        connection = HTTPConnection(scope)
        if connection.headers.get("content-type", "").split(";")[0] != (
            "application/x-www-form-urlencoded"
        ):
            return self.error("invalid_login", "Некорректная форма входа.", 415)
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return Response(status_code=499)
                    body.extend(message.get("body", b""))
                    if len(body) > 2048:
                        return self.error("invalid_login", "Форма слишком большая.", 413)
                    if not message.get("more_body", False):
                        break
            fields = parse_qs(body.decode("utf-8"), max_num_fields=2)
            supplied = fields.get("password", [""])
            valid = len(supplied) == 1 and hmac.compare_digest(
                supplied[0].encode("utf-8"), self.password
            )
        except (TimeoutError, ValueError, UnicodeError):
            return self.error("invalid_login", "Не удалось прочитать форму входа.", 400)
        if not valid:
            return self.login_page("Неверный пароль. Попробуйте ещё раз.", 401)
        response = RedirectResponse("/", status_code=303, headers={"Cache-Control": "no-store"})
        response.set_cookie(
            COOKIE_NAME,
            self.issue_cookie(),
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
        )
        return response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        authenticated = self.authenticated(connection)
        method = scope.get("method", "")
        path = scope["path"]
        if scope["type"] == "websocket":
            if not authenticated or connection.headers.get("origin") != self.origin:
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        response = None
        if path == "/health" and method in {"GET", "HEAD"} and not authenticated:
            response = JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})
        elif path == "/login" and method == "GET":
            response = (
                RedirectResponse("/", status_code=303) if authenticated else self.login_page()
            )
        elif path == "/login" and method == "POST":
            if connection.headers.get("origin") != self.origin:
                response = self.error("origin_denied", "Откройте форму входа на сайте Veyra.", 403)
            else:
                response = await self.login(scope, receive)
        elif not authenticated:
            if method == "GET" and "text/html" in connection.headers.get("accept", ""):
                response = RedirectResponse("/login", status_code=303)
            else:
                response = self.error(
                    "authentication_required", "Войдите для доступа к Veyra.", 401
                )
        elif method not in {"GET", "HEAD", "OPTIONS"} and (
            connection.headers.get("origin") != self.origin
        ):
            response = self.error("origin_denied", "Запрос с другого сайта запрещён.", 403)
        elif path == "/logout" and method == "POST":
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(
                COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict"
            )
        if response is not None:
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
