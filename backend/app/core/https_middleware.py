from fastapi.encoders import jsonable_encoder
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.context import request_id_context, trace_id_context

_HEALTH_PATHS = {"/api/v1/health", "/api/v1/ready"}


class HttpsEnforcementMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = request.app.state.settings
        if not settings.require_https or request.url.path in _HEALTH_PATHS:
            return await call_next(request)
        scheme = request.url.scheme.lower()
        if settings.trust_forwarded_proto:
            forwarded = request.headers.get("X-Forwarded-Proto", "")
            scheme = forwarded.partition(",")[0].strip().lower() or scheme
        if scheme == "https":
            return await call_next(request)
        return JSONResponse(
            status_code=426,
            content=jsonable_encoder(
                {
                    "error": {
                        "code": "HTTPS_REQUIRED",
                        "message": "HTTPS is required for this endpoint",
                        "details": None,
                        "request_id": request_id_context.get(),
                        "trace_id": trace_id_context.get(),
                    }
                }
            ),
        )
