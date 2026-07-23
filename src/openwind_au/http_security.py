"""HTTP request and response hardening for the public API."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Sequence
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_JSON_REQUEST_BYTES = 1024 * 1024
MAX_COMPLETED_RESULT_REQUEST_BYTES = 4 * 1024 * 1024
COMPLETED_RESULT_REPORT_PATHS = frozenset(
    {
        "/api/wind-workflow/result/report/html",
        "/api/wind-workflow/result/report/pdf",
    }
)
DEPLOYMENT_ENVIRONMENT_ENV = "OPENWIND_ENVIRONMENT"
TRUSTED_HOSTS_ENV = "OPENWIND_TRUSTED_HOSTS"
SUPPORTED_DEPLOYMENT_ENVIRONMENTS = frozenset({"development", "test", "production"})
DEFAULT_TRUSTED_HOSTS = ("127.0.0.1", "localhost", "testserver")


class DuplicateJsonMemberError(ValueError):
    """Raised when a JSON object repeats a member name."""


class NonFiniteJsonNumberError(ValueError):
    """Raised when JSON contains NaN, Infinity, or an overflowing number."""


def deployment_environment() -> str:
    """Return the validated deployment environment name."""

    value = os.environ.get(DEPLOYMENT_ENVIRONMENT_ENV, "development").strip().lower()
    if value not in SUPPORTED_DEPLOYMENT_ENVIRONMENTS:
        supported = ", ".join(sorted(SUPPORTED_DEPLOYMENT_ENVIRONMENTS))
        raise RuntimeError(f"{DEPLOYMENT_ENVIRONMENT_ENV} must be one of: {supported}.")
    return value


def production_mode() -> bool:
    """Return whether production-only API controls should be enabled."""

    return deployment_environment() == "production"


def configured_trusted_hosts(*, production: bool) -> list[str]:
    """Return an explicit TrustedHost allowlist for the REST API."""

    configured = os.environ.get(TRUSTED_HOSTS_ENV)
    if configured is None or not configured.strip():
        if production:
            raise RuntimeError(
                f"{TRUSTED_HOSTS_ENV} is required when {DEPLOYMENT_ENVIRONMENT_ENV}=production."
            )
        return list(DEFAULT_TRUSTED_HOSTS)

    hosts = [item.strip().lower() for item in configured.split(",")]
    if any(not host for host in hosts):
        raise RuntimeError(f"{TRUSTED_HOSTS_ENV} contains an empty host entry.")
    if len(hosts) > 64:
        raise RuntimeError(f"{TRUSTED_HOSTS_ENV} may contain at most 64 hosts.")
    for host in hosts:
        if len(host) > 253 or any(character.isspace() for character in host):
            raise RuntimeError(f"{TRUSTED_HOSTS_ENV} contains an invalid host.")
        if any(character in host for character in ("/", "@", "://")):
            raise RuntimeError(
                f"{TRUSTED_HOSTS_ENV} entries must be hostnames or IP addresses without ports."
            )
        if ":" in host:
            raise RuntimeError(
                f"{TRUSTED_HOSTS_ENV} entries must omit ports; IPv6 host patterns are not "
                "supported by the current server middleware."
            )
        if "*" in host and not (host.startswith("*.") and host.count("*") == 1):
            raise RuntimeError(
                f"{TRUSTED_HOSTS_ENV} only supports a leading '*.' subdomain wildcard."
            )
    if production and "*" in hosts:
        raise RuntimeError(f"{TRUSTED_HOSTS_ENV} must not allow every host in production.")
    return list(dict.fromkeys(hosts))


def _object_without_duplicate_members(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise DuplicateJsonMemberError("duplicate JSON object member")
        parsed[key] = value
    return parsed


def _reject_nonfinite_constant(_value: str) -> Any:
    raise NonFiniteJsonNumberError("non-finite JSON number")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise NonFiniteJsonNumberError("non-finite JSON number")
    return parsed


def validate_json_bytes(body: bytes) -> None:
    """Validate JSON syntax while rejecting duplicate and non-finite values."""

    if not body.strip():
        return
    json.loads(
        body,
        object_pairs_hook=_object_without_duplicate_members,
        parse_constant=_reject_nonfinite_constant,
        parse_float=_finite_json_float,
    )


def _is_json_media_type(content_type: str) -> bool:
    media_type = content_type.partition(";")[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


class BoundedJsonRequestMiddleware:
    """Bound request bodies and validate JSON before route parsing."""

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int = MAX_JSON_REQUEST_BYTES,
        completed_result_max_bytes: int = MAX_COMPLETED_RESULT_REQUEST_BYTES,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.completed_result_max_bytes = completed_result_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        path = str(scope.get("path", ""))
        max_bytes = (
            self.completed_result_max_bytes
            if path in COMPLETED_RESULT_REPORT_PATHS
            else self.max_bytes
        )
        content_type = headers.get("content-type", "")
        validate_as_json = _is_json_media_type(content_type)
        detect_json_without_media_type = not content_type.strip()

        declared_length = headers.get("content-length")
        if declared_length:
            try:
                content_length = int(declared_length)
            except ValueError:
                await self._error(send, 400, "Invalid Content-Length header.")
                return
            if content_length < 0:
                await self._error(send, 400, "Invalid Content-Length header.")
                return
            if content_length > max_bytes:
                await self._too_large(send, max_bytes)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > max_bytes:
                await self._too_large(send, max_bytes)
                return
            if not message.get("more_body", False):
                break

        try:
            if validate_as_json or detect_json_without_media_type:
                validate_json_bytes(bytes(body))
        except DuplicateJsonMemberError:
            await self._error(
                send,
                400,
                "JSON request body contains duplicate object member names.",
            )
            return
        except NonFiniteJsonNumberError:
            await self._error(send, 400, "JSON request body numbers must be finite.")
            return
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            if validate_as_json:
                await self._error(send, 400, "Malformed JSON request body.")
                return

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                # The original request stream has already been consumed. Delegate
                # subsequent reads so streaming responses can wait for the real
                # client disconnect instead of receiving an endless sequence of
                # completed request messages and spinning the event loop.
                return await receive()
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _too_large(self, send: Send, max_bytes: int) -> None:
        await self._error(
            send,
            413,
            f"Request body exceeds {max_bytes} bytes.",
        )

    @staticmethod
    async def _error(send: Send, status_code: int, detail: str) -> None:
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response(
            {"type": "http", "asgi": {"version": "3.0"}},
            _empty_receive,
            send,
        )


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


class SecurityHeadersMiddleware:
    """Add browser hardening and prevent caching of dynamic assessment data."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault(
                    "Permissions-Policy",
                    "camera=(), geolocation=(), microphone=()",
                )
                headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
                if _is_dynamic_path(path):
                    headers["Cache-Control"] = "no-store"
                    headers.setdefault("Pragma", "no-cache")
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _is_dynamic_path(path: str) -> bool:
    return not (path.startswith("/static/") or path == "/vendor/plotly.min.js")


class ProductionReadinessMiddleware:
    """Fail closed for production assessment APIs when shared readiness fails."""

    def __init__(
        self,
        app: ASGIApp,
        readiness_check: Callable[[], dict[str, Any]],
        exempt_api_paths: Sequence[str] = (),
    ) -> None:
        self.app = app
        self.readiness_check = readiness_check
        self.exempt_api_paths = frozenset(exempt_api_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        requires_readiness = (
            scope["type"] == "http"
            and path.startswith("/api/")
            and path not in self.exempt_api_paths
        )
        if not requires_readiness:
            await self.app(scope, receive, send)
            return

        try:
            report = self.readiness_check()
        except Exception:
            report = {"status": "not_ready"}
        if report.get("status") != "ready":
            response = JSONResponse(
                status_code=503,
                content={"detail": "Assessment service is not ready."},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
