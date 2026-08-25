from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.errors import ApplicationError
from app.schemas.plans import (
    PlanCreate,
    PlanResponse,
    PlanStepResponse,
    PlanStepTransitionRequest,
)
from app.services.plans import PlanService, PlanStepInput
from app.storage.models import PlanRecord
from app.storage.repositories import PlanRepository

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


async def to_plan_response(repository: PlanRepository, plan: PlanRecord) -> PlanResponse:
    steps = await repository.list_steps(plan.id)
    return PlanResponse(
        id=plan.id,
        incident_id=plan.incident_id,
        version=plan.version,
        objective=plan.objective,
        status=plan.status,
        max_tool_calls=plan.max_tool_calls,
        max_duration_seconds=plan.max_duration_seconds,
        replan_count=plan.replan_count,
        steps=[
            PlanStepResponse(
                id=step.id,
                ordinal=step.ordinal,
                title=step.title,
                objective=step.objective,
                kind=step.step_type,
                status=step.status,
                risk=step.risk,
                attempts=step.attempts,
                evidence_ids=step.evidence_ids,
                result_summary=step.result_summary,
                version=step.version,
                created_at=step.created_at,
                updated_at=step.updated_at,
            )
            for step in steps
        ],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.post(
    "/incidents/{incident_id}/plans",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_plan(
    incident_id: UUID,
    body: PlanCreate,
    session: Session,
) -> PlanResponse:
    plan_id = await PlanService(session).create(
        incident_id,
        body.objective,
        body.max_tool_calls,
        body.max_duration_seconds,
        [
            PlanStepInput(
                title=step.title,
                objective=step.objective,
                step_type=step.kind,
                dependencies=step.dependencies,
                resource_scope=step.resource_scope,
                allowed_capabilities=step.allowed_capabilities,
                expected_evidence=step.expected_evidence,
                success_criteria=step.success_criteria,
                risk=step.risk,
            )
            for step in body.steps
        ],
    )
    repository = PlanRepository(session)
    plan = await repository.get(plan_id)
    if plan is None:
        raise ApplicationError("PLAN_NOT_FOUND", "Plan does not exist", 404)
    return await to_plan_response(repository, plan)


@router.get("/incidents/{incident_id}/plans/current", response_model=PlanResponse)
async def get_current_plan(incident_id: UUID, session: Session) -> PlanResponse:
    repository = PlanRepository(session)
    plan = await repository.get_latest(incident_id)
    if plan is None:
        raise ApplicationError("PLAN_NOT_FOUND", "Incident has no plan", 404)
    return await to_plan_response(repository, plan)


@router.post(
    "/incidents/{incident_id}/steps/{step_id}/transitions",
    response_model=PlanResponse,
)
async def transition_step(
    incident_id: UUID,
    step_id: UUID,
    body: PlanStepTransitionRequest,
    session: Session,
) -> PlanResponse:
    await PlanService(session).transition_step(
        incident_id,
        step_id,
        body.target,
        body.expected_version,
        body.evidence_ids,
        body.result_summary,
    )
    repository = PlanRepository(session)
    plan = await repository.get_latest(incident_id)
    if plan is None:
        raise ApplicationError("PLAN_NOT_FOUND", "Incident has no plan", 404)
    return await to_plan_response(repository, plan)
