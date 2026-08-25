import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.engine import make_url

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class PostgresConnection:
    host: str
    port: int
    username: str
    password: str | None
    database: str

    @classmethod
    def parse(cls, value: str) -> "PostgresConnection":
        url = make_url(value)
        if url.get_backend_name() != "postgresql":
            raise ValueError("Backup and restore require a PostgreSQL database URL")
        if not url.username or not url.database:
            raise ValueError("PostgreSQL URL must include username and database")
        return cls(
            host=url.host or "localhost",
            port=url.port or 5432,
            username=url.username,
            password=url.password,
            database=url.database,
        )

    def client_arguments(self) -> list[str]:
        return [
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--username",
            self.username,
            "--dbname",
            self.database,
        ]

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        if self.password:
            environment["PGPASSWORD"] = self.password
        return environment


def create_backup(
    database_url: str,
    output: Path,
    *,
    pg_dump: str = "pg_dump",
) -> Path:
    connection = PostgresConnection.parse(database_url)
    output = output.resolve()
    if output.exists() or _manifest_path(output).exists():
        raise FileExistsError("Backup or manifest already exists; refusing to overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid4()}.tmp")
    try:
        _run(
            [
                pg_dump,
                *connection.client_arguments(),
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={temporary}",
            ],
            connection.environment(),
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("pg_dump did not create a non-empty backup")
        os.replace(temporary, output)
        manifest = {
            "format": "postgresql-custom",
            "version": 1,
            "createdAt": datetime.now(UTC).isoformat(),
            "databaseName": connection.database,
            "backupFile": output.name,
            "sizeBytes": output.stat().st_size,
            "sha256": _sha256(output),
        }
        _atomic_json(_manifest_path(output), manifest)
    except Exception:
        temporary.unlink(missing_ok=True)
        if output.exists() and not _manifest_path(output).exists():
            output.unlink()
        raise
    return _manifest_path(output)


def verify_backup(
    backup: Path,
    *,
    pg_restore: str = "pg_restore",
) -> dict[str, Any]:
    backup = backup.resolve()
    raw_manifest = json.loads(_manifest_path(backup).read_text(encoding="utf-8"))
    if not isinstance(raw_manifest, dict):
        raise ValueError("Backup manifest must contain an object")
    manifest = cast(dict[str, Any], raw_manifest)
    if manifest.get("format") != "postgresql-custom" or manifest.get("version") != 1:
        raise ValueError("Backup manifest format or version is unsupported")
    if manifest.get("backupFile") != backup.name:
        raise ValueError("Backup filename does not match manifest")
    if manifest.get("sizeBytes") != backup.stat().st_size:
        raise ValueError("Backup size does not match manifest")
    if manifest.get("sha256") != _sha256(backup):
        raise ValueError("Backup checksum does not match manifest")
    _run([pg_restore, "--list", str(backup)], os.environ.copy())
    return manifest


def restore_backup(
    backup: Path,
    target_url: str,
    *,
    confirmed_database: str,
    pg_restore: str = "pg_restore",
    psql: str = "psql",
) -> None:
    manifest = verify_backup(backup, pg_restore=pg_restore)
    target = PostgresConnection.parse(target_url)
    if target.database != confirmed_database:
        raise ValueError("Confirmed database name does not match the restore target")
    if target.database == manifest.get("databaseName"):
        raise ValueError("Restore target must not have the source database name")
    empty_check = _run(
        [
            psql,
            *target.client_arguments(),
            "--tuples-only",
            "--no-align",
            "--command",
            (
                "SELECT count(*) FROM pg_catalog.pg_tables "
                "WHERE schemaname NOT IN ('pg_catalog','information_schema');"
            ),
        ],
        target.environment(),
    )
    if empty_check.stdout.strip() != "0":
        raise ValueError("Restore target database is not empty")
    _run(
        [
            pg_restore,
            *target.client_arguments(),
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            str(backup.resolve()),
        ],
        target.environment(),
    )


def _run(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _manifest_path(backup: Path) -> Path:
    return backup.with_name(backup.name + ".manifest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as target:
            json.dump(payload, target, sort_keys=True, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, verify, or restore PostgreSQL backups")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--output", required=True, type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", required=True, type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--confirm-target-database", required=True)
    arguments = parser.parse_args()
    if arguments.command == "create":
        manifest = create_backup(get_settings().database_url, arguments.output)
        print(json.dumps({"manifestPath": str(manifest)}, separators=(",", ":")))
    elif arguments.command == "verify":
        print(json.dumps(verify_backup(arguments.backup), separators=(",", ":")))
    else:
        target_url = os.environ.get("OPSPILOT_RESTORE_DATABASE_URL")
        if not target_url:
            parser.error("OPSPILOT_RESTORE_DATABASE_URL is required for restore")
        restore_backup(
            arguments.backup,
            target_url,
            confirmed_database=arguments.confirm_target_database,
        )
        print(json.dumps({"restored": True}, separators=(",", ":")))


if __name__ == "__main__":
    main()
