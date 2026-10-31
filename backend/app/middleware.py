"""In-process request limits and optional administrative write protection."""

from __future__ import annotations

import math
import secrets
import time
from collections import defaultdict, deque
from typing import Deque

from starlette.responses import JSONResponse

_WINDOW_SECONDS = 60.0
_HEAVY_PATHS = {"/assistant/chat", "/advise", "/advise/v2", "/relief/run"}


class SecurityMiddleware:
    def __init__(
        self,
        app,
        *,
        requests_per_minute: int,
        heavy_requests_per_minute: int,
        max_request_body_bytes: int,
        admin_token: str,
        trust_proxy: bool,
    ) -> None:
        self.app = app
        self.requests_per_minute = max(1, requests_per_minute)
        self.heavy_requests_per_minute = max(1, heavy_requests_per_minute)
        self.max_request_body_bytes = max(1, max_request_body_bytes)
        self.admin_token = admin_token
        self.trust_proxy = trust_proxy
        self._windows: dict[tuple[str, str], Deque[float]] = defaultdict(deque)
        self._request_count = 0

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        if self.trust_proxy and headers.get(b"x-forwarded-for"):
            client_ip = headers[b"x-forwarded-for"].decode("latin-1").split(",", 1)[0].strip()
            client_ip = client_ip or (client[0] if client else "unknown")

        now = time.monotonic()
        self._request_count += 1
        if self._request_count % 256 == 0:
            for key, window in list(self._windows.items()):
                self._prune(window, now)
                if not window:
                    self._windows.pop(key, None)

        retry_after = self._consume(
            (client_ip, "general"),
            self.requests_per_minute,
            now,
        )
        heavy = path.startswith("/voice/") or path in _HEAVY_PATHS
        if retry_after is None and heavy:
            retry_after = self._consume(
                (client_ip, "heavy"),
                self.heavy_requests_per_minute,
                now,
            )
        if retry_after is not None:
            await self._respond(
                scope,
                receive,
                send,
                429,
                "Rate limit exceeded. Please retry later.",
                headers={"Retry-After": str(retry_after)},
            )
            return

        if self._requires_admin(method, path) and self.admin_token:
            provided_token = headers.get(b"x-admin-token", b"").decode("latin-1")
            if not secrets.compare_digest(provided_token, self.admin_token):
                await self._respond(
                    scope,
                    receive,
                    send,
                    401,
                    "A valid X-Admin-Token header is required.",
                )
                return

        body = b""
        content_type = headers.get(b"content-type", b"").lower()
        if content_type.startswith(b"application/json"):
            content_length = headers.get(b"content-length", b"")
            if content_length.isdigit() and int(content_length) > self.max_request_body_bytes:
                await self._respond(scope, receive, send, 413, "Request body exceeds the configured size limit.")
                return
            chunks = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(chunks) + len(chunk) > self.max_request_body_bytes:
                    await self._respond(scope, receive, send, 413, "Request body exceeds the configured size limit.")
                    return
                chunks.extend(chunk)
                if not message.get("more_body", False):
                    body = bytes(chunks)
                    break

        body_sent = False

        async def replay_body():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    ]
                )
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, replay_body, secure_send)

    def _consume(self, key: tuple[str, str], limit: int, now: float) -> int | None:
        window = self._windows[key]
        self._prune(window, now)
        if len(window) >= limit:
            return max(1, math.ceil(_WINDOW_SECONDS - (now - window[0])))
        window.append(now)
        return None

    @staticmethod
    def _prune(window: Deque[float], now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        while window and window[0] <= cutoff:
            window.popleft()

    @staticmethod
    def _requires_admin(method: str, path: str) -> bool:
        if method not in {"POST", "PATCH", "DELETE"}:
            return False
        if path == "/grid/sites":
            return method == "POST"
        if path.startswith("/grid/sites/"):
            return method == "DELETE"
        if path == "/grid/telemetry":
            return method in {"POST", "DELETE"}
        if path.startswith("/relief/"):
            return True
        return method == "DELETE" and path.startswith("/farms/") and path.count("/") == 2

    @staticmethod
    async def _respond(scope, receive, send, status_code: int, detail: str, headers=None) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"detail": detail},
            headers=headers,
        )

        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    ]
                )
                message = {**message, "headers": response_headers}
            await send(message)

        await response(scope, receive, secure_send)
