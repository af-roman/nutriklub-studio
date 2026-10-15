from __future__ import annotations

import os
import secrets
from base64 import b64decode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response


OPEN_PATHS = {"/healthz"}


def auth_enabled() -> bool:
    return bool((os.environ.get("STUDIO_USER") or "").strip())


def expected_credentials() -> tuple[str, str]:
    user = (os.environ.get("STUDIO_USER") or "").strip()
    password = os.environ.get("STUDIO_PASSWORD") or ""
    return user, password


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not auth_enabled():
            return await call_next(request)
        if request.url.path in OPEN_PATHS:
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                raw = b64decode(header[6:].encode("utf-8")).decode("utf-8")
            except Exception:
                raw = ""
            if ":" in raw:
                user, _, password = raw.partition(":")
                expected_user, expected_password = expected_credentials()
                user_ok = secrets.compare_digest(user, expected_user)
                pass_ok = secrets.compare_digest(password, expected_password)
                if user_ok and pass_ok:
                    return await call_next(request)

        return PlainTextResponse(
            "Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Studio"'},
        )
