from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.investigations import (
    InvestigationCheckpointCreate,
    InvestigationCheckpointResponse,
    InvestigationCheckpointWriteResponse,
    InvestigationHITLWaitCreate,
    InvestigationHITLWaitResponse,
    InvestigationHITLWaitWriteResponse,
    InvestigationRunResponse,
    InvestigationRunTransition,
)
from app.services.investigation_hitl import InvestigationHITLService
from app.services.investigations import InvestigationService

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/investigation-runs/{run_id}/hitl-waits",
    response_model=InvestigationHITLWaitWriteResponse,
)
async def start_investigation_hitl_wait(
    run_id: UUID,
    body: InvestigationHITLWaitCreate,
    session: Session,
) -> InvestigationHITLWaitWriteResponse:
    wait, duplicate = await InvestigationHITLService(session).start_wait(
        run_id=run_id,
        checkpoint_id=body.checkpoint_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        expected_run_version=body.expected_run_version,
    )
    return InvestigationHITLWaitWriteResponse(
        wait=InvestigationHITLWaitResponse.model_validate(wait), duplicate=duplicate
    )


@router.post(
    "/investigation-runs/{run_id}/transitions",
    response_model=InvestigationRunResponse,
)
async def transition_investigation_run(
    run_id: UUID,
    body: InvestigationRunTransition,
    session: Session,
) -> InvestigationRunResponse:
    run = await InvestigationService(session).transition_run(
        run_id=run_id,
        expected_version=body.expected_version,
        target=body.target,
        error_code=body.error_code,
    )
    return InvestigationRunResponse.model_validate(run)


@router.post(
    "/investigation-runs/{run_id}/checkpoints",
    response_model=InvestigationCheckpointWriteResponse,
)
async def write_investigation_checkpoint(
    run_id: UUID,
    body: InvestigationCheckpointCreate,
    session: Session,
) -> InvestigationCheckpointWriteResponse:
    result = await InvestigationService(session).write_checkpoint(
        run_id=run_id,
        node_execution_id=body.node_execution_id,
        expected_run_version=body.expected_run_version,
        node=body.node,
        iteration=body.iteration,
        plan_step_id=body.plan_step_id,
        hypothesis_ids=body.hypothesis_ids,
        evidence_ids=body.evidence_ids,
        completed_node_keys=body.completed_node_keys,
        no_progress_count=body.no_progress_count,
        progressed=body.progressed,
        next_action=body.next_action,
        model_requests=body.model_requests,
        model_input_tokens=body.model_input_tokens,
        model_output_tokens=body.model_output_tokens,
        output_summary=body.output_summary,
    )
    return InvestigationCheckpointWriteResponse(
        checkpoint=InvestigationCheckpointResponse.model_validate(result.checkpoint),
        duplicate=result.duplicate,
        run_version=result.run_version,
    )
