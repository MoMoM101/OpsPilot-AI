from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.api.pagination import PAGINATION_RESPONSE, set_pagination_headers
from app.core.errors import ApplicationError
from app.schemas.resources import (
    EnvironmentCreate,
    EnvironmentResponse,
    ResourceCreate,
    ResourceResponse,
)
from app.storage.repositories import EnvironmentRepository, ResourceRepository
from app.storage.transactions import commit_session

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/environments",
    response_model=EnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment(body: EnvironmentCreate, session: Session) -> EnvironmentResponse:
    repository = EnvironmentRepository(session)
    try:
        record = await repository.create(body.name, body.slug, body.description)
        await commit_session(session)
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError(
            "ENVIRONMENT_CONFLICT",
            "Environment name or slug already exists",
            status.HTTP_409_CONFLICT,
        ) from exc
    return EnvironmentResponse.model_validate(record)


@router.get(
    "/environments", response_model=list[EnvironmentResponse], responses=PAGINATION_RESPONSE
)
async def list_environments(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EnvironmentResponse]:
    repository = EnvironmentRepository(session)
    records = await repository.list(limit, offset)
    total = await repository.count()
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [EnvironmentResponse.model_validate(record) for record in records]


@router.post(
    "/resources",
    response_model=ResourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_resource(body: ResourceCreate, session: Session) -> ResourceResponse:
    if await EnvironmentRepository(session).get(body.environment_id) is None:
        raise ApplicationError("ENVIRONMENT_NOT_FOUND", "Environment does not exist", 404)
    repository = ResourceRepository(session)
    try:
        record = await repository.create(
            body.environment_id,
            body.name,
            body.kind,
            body.criticality,
            body.attributes,
        )
        await commit_session(session)
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError(
            "RESOURCE_CONFLICT",
            "Resource name already exists in this environment",
            status.HTTP_409_CONFLICT,
        ) from exc
    return ResourceResponse.model_validate(record)


@router.get("/resources", response_model=list[ResourceResponse], responses=PAGINATION_RESPONSE)
async def list_resources(
    session: Session,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ResourceResponse]:
    repository = ResourceRepository(session)
    records = await repository.list(limit, offset)
    total = await repository.count()
    set_pagination_headers(response, total=total, limit=limit, offset=offset)
    return [ResourceResponse.model_validate(record) for record in records]
