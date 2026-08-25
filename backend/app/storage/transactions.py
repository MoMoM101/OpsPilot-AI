from sqlalchemy.ext.asyncio import AsyncSession


async def commit_session(session: AsyncSession) -> None:
    """Commit background work, but defer HTTP request commits to its middleware."""
    if session.info.get("request_transaction"):
        await session.flush()
        return
    await session.commit()
