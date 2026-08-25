from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from app.core.errors import ApplicationError
from app.schemas.lab import LabScenarioMutationResponse, LabScenarioResponse


class LabControllerClient:
    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str | None,
        token: str | None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def list_scenarios(self) -> list[LabScenarioResponse]:
        payload = await self._request("GET", "/scenarios", None)
        try:
            return TypeAdapter(list[LabScenarioResponse]).validate_python(payload)
        except ValidationError as exc:
            raise self._invalid_response() from exc

    async def mutate(
        self, scenario_id: str, action: str, idempotency_key: str
    ) -> LabScenarioMutationResponse:
        if action not in {"inject", "cleanup"}:
            raise ValueError("Unsupported Lab mutation")
        payload = await self._request(
            "POST",
            f"/scenarios/{scenario_id}/{action}",
            {"idempotencyKey": idempotency_key},
        )
        try:
            return LabScenarioMutationResponse.model_validate(payload)
        except ValidationError as exc:
            raise self._invalid_response() from exc

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None
    ) -> Any:
        if not self.enabled or self.base_url is None or self.token is None:
            raise ApplicationError("LAB_DISABLED", "Fault Lab is not enabled", 404)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=body,
                    headers={"X-OpsPilot-Lab-Token": self.token},
                )
        except httpx.RequestError as exc:
            raise ApplicationError(
                "LAB_CONTROLLER_UNAVAILABLE", "Fault Lab controller is unavailable", 503
            ) from exc
        if response.status_code == 404:
            raise ApplicationError("LAB_SCENARIO_NOT_FOUND", "Lab scenario does not exist", 404)
        if response.status_code == 409:
            raise ApplicationError(
                "LAB_SCENARIO_CONFLICT", "Lab scenario state conflicts with this request", 409
            )
        if response.status_code != 200:
            raise ApplicationError(
                "LAB_CONTROLLER_ERROR", "Fault Lab controller rejected the request", 502
            )
        if len(response.content) > 262144:
            raise self._invalid_response()
        try:
            return response.json()
        except ValueError as exc:
            raise self._invalid_response() from exc

    @staticmethod
    def _invalid_response() -> ApplicationError:
        return ApplicationError(
            "LAB_CONTROLLER_INVALID_RESPONSE",
            "Fault Lab controller returned an invalid response",
            502,
        )
