import time
from typing import Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.redis_client import get_redis

log = structlog.get_logger()

RATE_LIMIT_RULES = {
    "/api/v1/auth/login": (settings.RATE_LIMIT_LOGIN, 60),
    "/api/v1/sms/report": (settings.RATE_LIMIT_SMS_REPORT, 60),
    "/api/v1/sms/report/batch": (settings.RATE_LIMIT_SMS_REPORT, 60),
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        rule = RATE_LIMIT_RULES.get(path)

        if rule:
            max_req, window = rule
            # Use device key if present, else IP
            identifier = request.headers.get("X-Device-Key", request.client.host)
            redis_key = f"rl:{path}:{identifier}"

            try:
                redis = await get_redis()
                pipe = redis.pipeline()
                pipe.incr(redis_key)
                pipe.expire(redis_key, window)
                results = await pipe.execute()
                count = results[0]

                if count > max_req:
                    return Response(
                        content='{"detail":"Rate limit exceeded"}',
                        status_code=429,
                        media_type="application/json",
                        headers={"Retry-After": str(window)},
                    )
            except Exception:
                log.warning("rate_limit_check_failed", path=path)

        return await call_next(request)


class AuditMiddleware(BaseHTTPMiddleware):
    """Attach request metadata to context for downstream audit logging."""

    SENSITIVE_PATHS = {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/2fa/enable",
        "/api/v1/auth/2fa/disable",
        "/api/v1/admin",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request.state.client_ip = (
            request.headers.get("X-Forwarded-For", request.client.host).split(",")[0].strip()
        )
        request.state.user_agent = request.headers.get("User-Agent", "")
        return await call_next(request)
