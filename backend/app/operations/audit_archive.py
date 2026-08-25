import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings
from app.services.audit_archiving import AuditArchiveService
from app.storage.database import Database


async def _archive(directory: Path, retention_days: int | None, batch_size: int | None) -> int:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            result = await AuditArchiveService(session).archive_before(
                datetime.now(UTC)
                - timedelta(days=retention_days or settings.audit_retention_days),
                directory,
                batch_size=batch_size or settings.audit_archive_batch_size,
            )
    finally:
        await database.dispose()
    payload = (
        {"archived": False, "recordCount": 0}
        if result is None
        else {
            "archived": True,
            "batchId": str(result.batch_id),
            "recordCount": result.record_count,
            "contentSha256": result.content_sha256,
            "path": str(result.path),
            "manifestPath": str(result.manifest_path),
        }
    )
    print(json.dumps(payload, separators=(",", ":")))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive expired Control Plane audit rows")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--retention-days", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--verify", type=Path)
    arguments = parser.parse_args()
    if arguments.verify is not None:
        manifest = AuditArchiveService.verify(arguments.verify)
        print(json.dumps(manifest, separators=(",", ":")))
        return
    if arguments.directory is None:
        parser.error("--directory is required when archiving")
    if arguments.retention_days is not None and arguments.retention_days < 30:
        parser.error("--retention-days must be at least 30")
    if arguments.batch_size is not None and not 1 <= arguments.batch_size <= 100000:
        parser.error("--batch-size must be between 1 and 100000")
    raise SystemExit(
        asyncio.run(_archive(arguments.directory, arguments.retention_days, arguments.batch_size))
    )


if __name__ == "__main__":
    main()
