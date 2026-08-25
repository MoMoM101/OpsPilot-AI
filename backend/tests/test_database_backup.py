import json
import subprocess
from pathlib import Path

import pytest

from app.operations import database_backup


def test_backup_uses_password_environment_and_writes_verifiable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(
        arguments: list[str], environment: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, environment))
        output = next(
            (
                item.removeprefix("--file=")
                for item in arguments
                if item.startswith("--file=")
            ),
            None,
        )
        if output is not None:
            Path(output).write_bytes(b"postgres-custom-backup")
        return subprocess.CompletedProcess(arguments, 0, stdout="archive list", stderr="")

    monkeypatch.setattr(database_backup, "_run", fake_run)
    backup = tmp_path / "opspilot.dump"
    manifest_path = database_backup.create_backup(
        "postgresql+asyncpg://operator:top-secret@db.internal:5433/source_db",
        backup,
    )
    manifest = database_backup.verify_backup(backup)

    assert manifest_path.is_file()
    assert manifest["databaseName"] == "source_db"
    assert manifest["sizeBytes"] == backup.stat().st_size
    assert all("top-secret" not in argument for call, _ in calls for argument in call)
    assert calls[0][1]["PGPASSWORD"] == "top-secret"


def test_restore_requires_confirmed_empty_different_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = tmp_path / "opspilot.dump"
    backup.write_bytes(b"postgres-custom-backup")
    manifest = {
        "format": "postgresql-custom",
        "version": 1,
        "createdAt": "2026-08-20T00:00:00+00:00",
        "databaseName": "source_db",
        "backupFile": backup.name,
        "sizeBytes": backup.stat().st_size,
        "sha256": database_backup._sha256(backup),
    }
    database_backup._manifest_path(backup).write_text(json.dumps(manifest), encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(
        arguments: list[str], _environment: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        stdout = "0\n" if arguments[0] == "psql" else "ok"
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(database_backup, "_run", fake_run)
    target = "postgresql://restore:target-secret@db.internal/restore_drill"
    database_backup.restore_backup(
        backup,
        target,
        confirmed_database="restore_drill",
    )

    assert [call[0] for call in calls] == ["pg_restore", "psql", "pg_restore"]
    assert all("target-secret" not in argument for call in calls for argument in call)
    with pytest.raises(ValueError, match="Confirmed database name"):
        database_backup.restore_backup(backup, target, confirmed_database="wrong_database")
    with pytest.raises(ValueError, match="source database name"):
        database_backup.restore_backup(
            backup,
            "postgresql://restore@db.internal/source_db",
            confirmed_database="source_db",
        )
