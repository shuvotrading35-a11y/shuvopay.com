import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

log = structlog.get_logger()


class AppException(Exception):
    def __init__(self, status_code: int, detail: str, code: str = None):
        self.status_code = status_code
        self.detail = detail
        self.code = code


class NotFoundError(AppException):
    def __init__(self, resource: str):
        super().__init__(404, f"{resource} not found", "NOT_FOUND")


class UnauthorizedError(AppException):
    def __init__(self, msg: str = "Unauthorized"):
        super().__init__(401, msg, "UNAUTHORIZED")


class ForbiddenError(AppException):
    def __init__(self, msg: str = "Forbidden"):
        super().__init__(403, msg, "FORBIDDEN")


class ConflictError(AppException):
    def __init__(self, msg: str):
        super().__init__(409, msg, "CONFLICT")


class RateLimitError(AppException):
    def __init__(self):
        super().__init__(429, "Rate limit exceeded", "RATE_LIMITED")


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        log.warning("app_exception", status=exc.status_code, detail=exc.detail, path=request.url.path)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        log.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
