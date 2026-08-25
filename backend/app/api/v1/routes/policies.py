from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.schemas.policies import (
    PolicyDecisionResponse,
    PolicyDecisionSnapshotResponse,
    PolicyDryRunRequest,
    PolicyEvaluateRequest,
    PolicyRuleCreate,
    PolicyRuleResponse,
    PolicyRuleUpdate,
)
from app.services.policies import PolicyService
from app.storage.repositories import PolicyRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
UUIDQuery = Annotated[UUID, Query(alias="environmentId")]


@router.post("/policies", response_model=PolicyRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(body: PolicyRuleCreate, session: Session) -> PolicyRuleResponse:
    record = await PolicyService(session).create_rule(
        environment_id=body.environment_id,
        name=body.name,
        description=body.description,
        priority=body.priority,
        enabled=body.enabled,
        effect=body.effect,
        autonomy_levels=[item.value for item in body.autonomy_levels],
        risk_levels=[item.value for item in body.risk_levels],
        capabilities=body.capabilities,
        resource_ids=body.resource_ids,
        approval_required=body.approval_required,
        maintenance_days=body.maintenance_days,
        maintenance_start_minute=body.maintenance_start_minute,
        maintenance_end_minute=body.maintenance_end_minute,
        max_executions_per_incident=body.max_executions_per_incident,
    )
    return PolicyRuleResponse.model_validate(record)


@router.get("/policies", response_model=list[PolicyRuleResponse], responses=PAGINATION_RESPONSE)
async def list_policies(
    environment_id: UUIDQuery,
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PolicyRuleResponse]:
    repository = PolicyRepository(session)
    records = await repository.list_for_environment(
        environment_id, limit=limit, offset=offset
    )
    total = await repository.count_for_environment(environment_id)
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [PolicyRuleResponse.model_validate(item) for item in records]


@router.put("/policies/{policy_id}", response_model=PolicyRuleResponse)
async def update_policy(
    policy_id: UUID, body: PolicyRuleUpdate, session: Session
) -> PolicyRuleResponse:
    record = await PolicyService(session).update_rule(
        policy_id,
        expected_version=body.expected_version,
        environment_id=body.environment_id,
        name=body.name,
        description=body.description,
        priority=body.priority,
        enabled=body.enabled,
        effect=body.effect,
        autonomy_levels=[item.value for item in body.autonomy_levels],
        risk_levels=[item.value for item in body.risk_levels],
        capabilities=body.capabilities,
        resource_ids=body.resource_ids,
        approval_required=body.approval_required,
        maintenance_days=body.maintenance_days,
        maintenance_start_minute=body.maintenance_start_minute,
        maintenance_end_minute=body.maintenance_end_minute,
        max_executions_per_incident=body.max_executions_per_incident,
    )
    return PolicyRuleResponse.model_validate(record)


@router.post("/policies/dry-run", response_model=PolicyDecisionResponse)
async def dry_run_policy(body: PolicyDryRunRequest, session: Session) -> PolicyDecisionResponse:
    decision = await PolicyService(session).dry_run(
        environment_id=body.environment_id,
        resource_id=body.resource_id,
        capability=body.capability,
        autonomy_level=body.autonomy_level,
        risk=body.risk,
    )
    return PolicyDecisionResponse.model_validate(decision)


@router.post("/policies/evaluate", response_model=PolicyDecisionSnapshotResponse)
async def evaluate_policy(
    body: PolicyEvaluateRequest, session: Session
) -> PolicyDecisionSnapshotResponse:
    decision, snapshot_id, evaluated_at = await PolicyService(session).evaluate(
        environment_id=body.environment_id,
        incident_id=body.incident_id,
        resource_id=body.resource_id,
        capability=body.capability,
        autonomy_level=body.autonomy_level,
        risk=body.risk,
    )
    payload = PolicyDecisionResponse.model_validate(decision).model_dump()
    return PolicyDecisionSnapshotResponse(
        **payload, snapshot_id=snapshot_id, evaluated_at=evaluated_at
    )
