from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260820_0035_control_plane_setup.py"
    )
    spec = importlib.util.spec_from_file_location("control_plane_setup_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _connection() -> sa.Connection:
    connection = sa.create_engine("sqlite://").connect()
    connection.execute(
        sa.text(
            """
            CREATE TABLE api_principals (
                id CHAR(32) PRIMARY KEY,
                created_at DATETIME NOT NULL,
                kind VARCHAR(20) NOT NULL,
                role VARCHAR(20) NOT NULL,
                active BOOLEAN NOT NULL
            )
            """
        )
    )
    return connection


def _upgrade(connection: sa.Connection) -> None:
    module = _migration_module()
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


def test_setup_migration_marks_historical_admin_as_consumed() -> None:
    connection = _connection()
    admin_id = uuid4().hex
    connection.execute(
        sa.text(
            """
            INSERT INTO api_principals (id, created_at, kind, role, active)
            VALUES (:id, '2026-08-01 00:00:00', 'user', 'admin', TRUE)
            """
        ),
        {"id": admin_id},
    )

    _upgrade(connection)

    row = connection.execute(
        sa.text(
            "SELECT completed_at, completed_by_principal_id "
            "FROM control_plane_setup WHERE key = 'initial_admin'"
        )
    ).one()
    assert row.completed_at is not None
    assert str(row.completed_by_principal_id).replace("-", "") == admin_id


def test_setup_migration_leaves_fresh_install_pending() -> None:
    connection = _connection()

    _upgrade(connection)

    row = connection.execute(
        sa.text(
            "SELECT completed_at, completed_by_principal_id "
            "FROM control_plane_setup WHERE key = 'initial_admin'"
        )
    ).one()
    assert row.completed_at is None
    assert row.completed_by_principal_id is None
