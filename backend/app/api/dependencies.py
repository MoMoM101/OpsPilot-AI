from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    request_session = getattr(request.state, "db_session", None)
    if request_session is not None:
        yield request_session
        return
    async for session in request.app.state.database.session():
        yield session
