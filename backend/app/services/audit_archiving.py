import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import ControlPlaneAuditRecord
from app.storage.repositories import AuditArchiveRepository, AuditRepository


@dataclass(frozen=True, slots=True)
class AuditArchiveResult:
    batch_id: UUID
    path: Path
    manifest_path: Path
    record_count: int
    content_sha256: str


class AuditArchiveService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditRepository(session)
        self.archives = AuditArchiveRepository(session)

    async def archive_before(
        self,
        cutoff: datetime,
        directory: Path,
        *,
        batch_size: int,
    ) -> AuditArchiveResult | None:
        records = await self.audit.list_before(cutoff, batch_size, for_update=True)
        if not records:
            return None
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        batch_id = uuid4()
        stem = f"control-plane-audit-{records[0].occurred_at:%Y%m%dT%H%M%S}-{batch_id}"
        archive_path = directory / f"{stem}.jsonl.gz"
        manifest_path = directory / f"{stem}.manifest.json"
        payload = b"".join(self._line(record) for record in records)
        digest = hashlib.sha256(payload).hexdigest()
        manifest = {
            "format": "opspilot-control-plane-audit-jsonl-gzip",
            "version": 1,
            "batchId": str(batch_id),
            "createdAt": datetime.now(UTC).isoformat(),
            "cutoffAt": cutoff.isoformat(),
            "recordCount": len(records),
            "contentSha256": digest,
            "archiveFile": archive_path.name,
        }
        try:
            self._write_archive(archive_path, payload)
            self._write_manifest(manifest_path, manifest)
            now = datetime.now(UTC)
            await self.archives.create(
                id=batch_id,
                created_at=now,
                cutoff_at=cutoff,
                first_occurred_at=records[0].occurred_at,
                last_occurred_at=records[-1].occurred_at,
                record_count=len(records),
                content_sha256=digest,
                storage_uri=archive_path.as_uri(),
            )
            deleted = await self.audit.delete_ids([record.id for record in records])
            if deleted != len(records):
                raise RuntimeError("Audit archive source rows changed during archival")
        except Exception:
            await self.session.rollback()
            archive_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            raise
        try:
            await self.session.commit()
        except Exception:
            # Commit acknowledgement can be ambiguous. Preserve the durable archive so a
            # database-side commit can never leave deleted audit rows without an export.
            await self.session.rollback()
            raise
        return AuditArchiveResult(
            batch_id=batch_id,
            path=archive_path,
            manifest_path=manifest_path,
            record_count=len(records),
            content_sha256=digest,
        )

    @staticmethod
    def verify(archive_path: Path, manifest_path: Path | None = None) -> dict[str, object]:
        resolved_manifest = manifest_path or archive_path.with_name(
            archive_path.name.removesuffix(".jsonl.gz") + ".manifest.json"
        )
        raw_manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        if not isinstance(raw_manifest, dict):
            raise ValueError("Audit archive manifest must contain an object")
        manifest = cast(dict[str, object], raw_manifest)
        if (
            manifest.get("format") != "opspilot-control-plane-audit-jsonl-gzip"
            or manifest.get("version") != 1
        ):
            raise ValueError("Audit archive manifest format or version is unsupported")
        with gzip.open(archive_path, "rb") as source:
            payload = source.read()
        digest = hashlib.sha256(payload).hexdigest()
        lines = [line for line in payload.splitlines() if line]
        if digest != manifest.get("contentSha256"):
            raise ValueError("Audit archive checksum does not match its manifest")
        if len(lines) != manifest.get("recordCount"):
            raise ValueError("Audit archive record count does not match its manifest")
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Audit archive contains a non-object record")
        return manifest

    @staticmethod
    def _line(record: ControlPlaneAuditRecord) -> bytes:
        payload = {
            "id": str(record.id),
            "occurredAt": record.occurred_at.isoformat(),
            "actorId": record.actor_id,
            "actorType": record.actor_type,
            "actorRole": record.actor_role,
            "method": record.method,
            "path": record.path,
            "statusCode": record.status_code,
            "requestId": record.request_id,
            "traceId": record.trace_id,
            "action": record.action,
            "outcome": record.outcome,
            "errorCode": record.error_code,
            "sourceIp": record.source_ip,
            "userAgentHash": record.user_agent_hash,
        }
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()

    @staticmethod
    def _write_archive(path: Path, payload: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                with gzip.GzipFile(fileobj=temporary, mode="wb", mtime=0) as archive:
                    archive.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
        encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
