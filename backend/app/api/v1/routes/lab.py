from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.schemas.lab import (
    LabScenarioMutationRequest,
    LabScenarioMutationResponse,
    LabScenarioResponse,
)
from app.services.lab import LabControllerClient

router = APIRouter()


def _client(request: Request) -> LabControllerClient:
    settings = request.app.state.settings
    return LabControllerClient(
        enabled=settings.lab_enabled,
        base_url=str(settings.lab_controller_url) if settings.lab_controller_url else None,
        token=settings.lab_controller_token,
        timeout_seconds=settings.lab_controller_timeout_seconds,
    )


LabClient = Annotated[LabControllerClient, Depends(_client)]


@router.get("/lab/scenarios", response_model=list[LabScenarioResponse])
async def list_lab_scenarios(client: LabClient) -> list[LabScenarioResponse]:
    return await client.list_scenarios()


@router.post(
    "/lab/scenarios/{scenario_id}/inject",
    response_model=LabScenarioMutationResponse,
)
async def inject_lab_scenario(
    scenario_id: str,
    body: LabScenarioMutationRequest,
    client: LabClient,
) -> LabScenarioMutationResponse:
    return await client.mutate(scenario_id, "inject", body.idempotency_key)


@router.post(
    "/lab/scenarios/{scenario_id}/cleanup",
    response_model=LabScenarioMutationResponse,
)
async def cleanup_lab_scenario(
    scenario_id: str,
    body: LabScenarioMutationRequest,
    client: LabClient,
) -> LabScenarioMutationResponse:
    return await client.mutate(scenario_id, "cleanup", body.idempotency_key)
