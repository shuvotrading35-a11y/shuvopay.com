import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from app.api.v1 import router as api_v1_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import AuditMiddleware, RateLimitMiddleware
from app.db.session import engine, Base
from app.core.logging_config import configure_logging

configure_logging()
log = structlog.get_logger()

REQUEST_COUNT = Counter(
    "api_requests_total", "Total API requests", ["method", "endpoint", "status"]
)
REQUEST_DURATION = Histogram(
    "api_request_duration_seconds", "API request duration", ["method", "endpoint"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", service="shuvopay-backend")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    log.info("shutdown", service="shuvopay-backend")


app = FastAPI(
    title="ShuvoPay API",
    description="SMS-based payment verification platform",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)
app.add_middleware(RateLimitMiddleware)

register_exception_handlers(app)

app.include_router(api_v1_router, prefix="/api/v1")


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id

    with structlog.contextvars.bound_contextvars(trace_id=trace_id):
        response: Response = await call_next(request)

    duration = time.time() - start
    endpoint = request.url.path
    REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
    REQUEST_DURATION.labels(request.method, endpoint).observe(duration)

    response.headers["X-Trace-ID"] = trace_id
    return response


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
async def readiness():
    from app.db.session import async_session
    from app.core.redis_client import get_redis

    try:
        async with async_session() as session:
            from sqlalchemy import text
await session.execute(text("SELECT 1"))
        redis = await get_redis()
        await redis.ping()
        return {"status": "ready", "db": "ok", "redis": "ok"}
    except Exception as e:
        return Response(
            content=f'{{"status":"not_ready","error":"{str(e)}"}}',
            status_code=503,
            media_type="application/json",
        )


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
