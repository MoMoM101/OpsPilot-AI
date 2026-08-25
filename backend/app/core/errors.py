from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.core.context import request_id_context, trace_id_context
from app.core.logging import get_logger

logger = get_logger(__name__)


class ValidationIssueResponse(BaseModel):
    type: str
    location: list[str | int]
    message: str


class ValidationErrorDetailResponse(BaseModel):
    code: str
    message: str
    details: list[ValidationIssueResponse]
    request_id: str | None
    trace_id: str | None


class ValidationErrorResponse(BaseModel):
    error: ValidationErrorDetailResponse


def _safe_validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for issue in exc.errors():
        location = [part if isinstance(part, int) else str(part) for part in issue.get("loc", ())]
        details.append(
            {
                "type": str(issue.get("type", "validation_error")),
                "location": location,
                "message": str(issue.get("msg", "Invalid input")),
            }
        )
    return details


class ApplicationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id_context.get(),
            "trace_id": trace_id_context.get(),
        }
    }


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(f"HTTP_{exc.status_code}", message, exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_body(
                "VALIDATION_ERROR", "Request validation failed", _safe_validation_details(exc)
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("INTERNAL_ERROR", "An unexpected error occurred"),
        )
