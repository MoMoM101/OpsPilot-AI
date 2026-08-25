from time import perf_counter
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import bind_request_context, reset_request_context
from app.core.logging import get_logger

logger = get_logger(__name__)


def _valid_id(value: str | None) -> str:
    if not value:
        return str(uuid4())
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _valid_id(request.headers.get("X-Request-ID"))
        trace_id = _valid_id(request.headers.get("X-Trace-ID"))
        tokens = bind_request_context(request_id, trace_id)
        started_at = perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = trace_id
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            return response
        finally:
            reset_request_context(tokens)
