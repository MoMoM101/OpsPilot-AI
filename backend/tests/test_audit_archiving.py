import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.services.audit_archiving import AuditArchiveService
from app.storage import Base
from app.storage.database import Database
from app.storage.models import AuditArchiveBatchRecord, ControlPlaneAuditRecord


def _audit(occurred_at: datetime, actor_id: str) -> ControlPlaneAuditRecord:
    return ControlPlaneAuditRecord(
        occurred_at=occurred_at,
        actor_id=actor_id,
        actor_type="user",
        actor_role="admin",
        method="POST",
        path="/api/v1/incidents",
        status_code=201,
        request_id=None,
        trace_id=None,
        action="http.write",
        outcome="success",
        error_code=None,
        source_ip="127.0.0.1",
        user_agent_hash=None,
    )


def test_audit_archive_is_verified_before_old_rows_are_removed(tmp_path: Path) -> None:
    async def scenario() -> tuple[int, int, Path, Path]:
        database = Database(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
        now = datetime.now(UTC)
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            session.add_all(
                [
                    _audit(now - timedelta(days=400), "old-1"),
                    _audit(now - timedelta(days=399), "old-2"),
                    _audit(now - timedelta(days=1), "recent"),
                ]
            )
            await session.commit()
        async with database.session_factory() as session:
            result = await AuditArchiveService(session).archive_before(
                now - timedelta(days=365),
                tmp_path / "archive",
                batch_size=100,
            )
            assert result is not None
        async with database.session_factory() as session:
            audit_count = int(
                await session.scalar(select(func.count()).select_from(ControlPlaneAuditRecord))
                or 0
            )
            batch_count = int(
                await session.scalar(select(func.count()).select_from(AuditArchiveBatchRecord))
                or 0
            )
        await database.dispose()
        return audit_count, batch_count, result.path, result.manifest_path

    audit_count, batch_count, archive, manifest = asyncio.run(scenario())

    verified = AuditArchiveService.verify(archive, manifest)
    assert audit_count == 1
    assert batch_count == 1
    assert verified["recordCount"] == 2
    assert verified["archiveFile"] == archive.name


def test_audit_archive_checksum_detects_manifest_tampering(tmp_path: Path) -> None:
    archive = tmp_path / "audit.jsonl.gz"
    AuditArchiveService._write_archive(archive, b'{"id":"one"}\n')
    manifest = tmp_path / "audit.manifest.json"
    AuditArchiveService._write_manifest(
        manifest,
        {
            "format": "opspilot-control-plane-audit-jsonl-gzip",
            "version": 1,
            "contentSha256": "0" * 64,
            "recordCount": 1,
        },
    )

    try:
        AuditArchiveService.verify(archive, manifest)
    except ValueError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("Tampered manifest must fail verification")
