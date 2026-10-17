"""Request logging and error handling, without personal data in the logs.

- One log line per request: method, the matched *route template* (e.g. /app/profiles/{profile_id}), status,
  duration and a request id. Query strings and raw paths are never logged, because filters and searches
  carry emails (?email=..., /app/profiles/search?q=...). Uvicorn's own access log is turned off for the
  same reason (see deploy/start.sh), and Nginx logs $uri without the query string.
- Every response carries X-Request-ID. A caller may send its own (letters, digits and dashes, 8-64 long).
- Unhandled errors return {"detail": ..., "request_id": ...} with status 500 and log the traceback under
  that id, so a user report can be matched to the log without the log holding what they sent.

Error conventions for everything else: 400 bad input (detail is a message or {message, errors}),
401 not signed in or bad signature, 403 not allowed, 404 unknown id, 409 conflict, 413 too large,
422 request didn't match the schema (FastAPI's standard shape), 429 rate limited (with Retry-After),
503 a dependency (OpenAI, Google) isn't configured or reachable.
"""

import logging
import re
import sys
import time
import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

log = logging.getLogger("cdp.request")


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger("cdp")
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


def route_template(scope: Scope) -> str:
    """The matched route's path template, e.g. /app/profiles/{profile_id}. A raw path could contain anything.

    Routes in included routers and mounted apps (like the admin) only know their path below the prefix, so the
    prefix is taken from the leading segments of the real path: prefixes are always literal, never parameters.
    """
    route = scope.get("route")
    template = getattr(route, "path", None)
    if template is None:
        return "(no route)"
    path_segments = scope.get("path", "").strip("/").split("/")
    template_segments = [s for s in template.strip("/").split("/") if s]
    prefix = path_segments[: max(len(path_segments) - len(template_segments), 0)]
    return "/" + "/".join([s for s in prefix if s] + template_segments)


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(REQUEST_ID_HEADER.lower().encode(), b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (REQUEST_ID_HEADER.lower().encode(), request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if route_template(scope) != "/app/health":  # the platform polls this every few seconds
                log.info(
                    "%s %s %s %dms rid=%s",
                    scope["method"],
                    route_template(scope),
                    status,
                    (time.perf_counter() - started) * 1000,
                    request_id,
                )


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "") or uuid.uuid4().hex


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_of(request)
    # The stack frames, not the exception message: messages can quote data (SQLAlchemy errors include the
    # statement's parameters, which may be emails).
    frames = "".join(traceback.format_tb(exc.__traceback__))
    logging.getLogger("cdp.error").error(
        "unhandled %s on %s %s rid=%s\n%s",
        type(exc).__name__,
        request.method,
        route_template(request.scope),
        request_id,
        frames,
    )
    return JSONResponse(
        {"detail": f"Something went wrong on our side. Reference: {request_id}", "request_id": request_id},
        status_code=500,
        headers={REQUEST_ID_HEADER: request_id},
    )


def install(app: FastAPI) -> None:
    configure_logging()
    app.add_middleware(RequestLogMiddleware)
    app.add_exception_handler(Exception, unhandled_error)
