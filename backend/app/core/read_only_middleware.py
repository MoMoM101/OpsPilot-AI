import re

from fastapi.encoders import jsonable_encoder
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.context import request_id_context, trace_id_context

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_RECOVERY_PATH = "/api/v1/system/recovery"
_MODEL_DIAGNOSTIC_PATH = "/api/v1/system/model-connection-check"
_AUTH_PATHS = {
    "/api/v1/auth/session",
    "/api/v1/auth/session/refresh",
}
_RUNNER_ACTION_CLAIM = re.compile(
    r"^/runner/v1/runners/[0-9a-f-]+/actions/claim$",
    re.IGNORECASE,
)


class ReadOnlyControlPlaneMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        mode = request.app.state.control_plane_mode
        if (
            mode.writable()
            or request.method in _SAFE_METHODS
            or (
                not request.url.path.startswith("/api/v1/")
                and not _RUNNER_ACTION_CLAIM.match(request.url.path)
            )
            or request.url.path == _RECOVERY_PATH
            or request.url.path == _MODEL_DIAGNOSTIC_PATH
            or request.url.path in _AUTH_PATHS
        ):
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content=jsonable_encoder(
                {
                    "error": {
                        "code": "CONTROL_PLANE_READ_ONLY",
                        "message": "Control Plane is read-only until recovery succeeds",
                        "details": {"reasonCode": mode.reason_code},
                        "request_id": request_id_context.get(),
                        "trace_id": trace_id_context.get(),
                    }
                }
            ),
            headers={"Retry-After": "30"},
        )
