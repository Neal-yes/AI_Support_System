from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from typing import Optional
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import JSONResponse as StarletteJSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _json_error(status_code: int, error: str, detail: object, request_id: Optional[str]) -> JSONResponse:
    payload = {
        "error": error,
        "detail": detail,
    }
    if request_id:
        payload["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=payload)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        rid = getattr(request.state, "request_id", None)
        # validation and HTTP errors as warning
        logger.warning(
            "http_error",
            extra={
                "request_id": rid,
                "status_code": exc.status_code,
                "detail": exc.detail,
                "path": request.url.path,
                "method": request.method,
            },
        )
        return _json_error(exc.status_code, "HTTPError", exc.detail, rid)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", None)
        logger.warning(
            "validation_error",
            extra={
                "request_id": rid,
                "errors": exc.errors(),
                "path": request.url.path,
                "method": request.method,
            },
        )
        return _json_error(422, "ValidationError", exc.errors(), rid)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None)
        logger.exception(
            "unhandled_exception",
            extra={
                "request_id": rid,
                "path": request.url.path,
                "method": request.method,
            },
        )
        # 不暴露内部细节，只给出通用提示
        return _json_error(500, "InternalServerError", "Internal Server Error", rid)
