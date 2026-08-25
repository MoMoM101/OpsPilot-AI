from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.storage.base import Base


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260814_0032_policy_constraint_name.py"
    )
    spec = importlib.util.spec_from_file_location("policy_constraint_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _connection(*, constraint_name: str | None = None) -> sa.Connection:
    connection = sa.create_engine("sqlite://").connect()
    constraint = (
        f", CONSTRAINT {constraint_name} CHECK (effect IN ('allow', 'deny'))"
        if constraint_name is not None
        else ""
    )
    connection.execute(
        sa.text(
            "CREATE TABLE policy_rules ("
            "id TEXT PRIMARY KEY, effect TEXT NOT NULL"
            f"{constraint})"
        )
    )
    return connection


def _run(connection: sa.Connection, operation: str) -> None:
    module = _migration_module()
    context = MigrationContext.configure(
        connection,
        opts={"target_metadata": Base.metadata},
    )
    module.__dict__["op"] = Operations(context)
    getattr(module, operation)()


def _constraint_names(connection: sa.Connection) -> set[str]:
    return {
        name
        for constraint in sa.inspect(connection).get_check_constraints("policy_rules")
        if (name := constraint.get("name")) is not None
    }


def test_upgrade_creates_target_constraint_when_legacy_is_missing() -> None:
    connection = _connection()

    _run(connection, "upgrade")

    assert _constraint_names(connection) == {"ck_policy_rules_policy_effect"}


def test_upgrade_replaces_legacy_constraint_and_is_idempotent() -> None:
    connection = _connection(constraint_name="policy_effect")

    _run(connection, "upgrade")
    _run(connection, "upgrade")

    assert _constraint_names(connection) == {"ck_policy_rules_policy_effect"}


def test_downgrade_restores_legacy_constraint() -> None:
    connection = _connection(constraint_name="ck_policy_rules_policy_effect")

    _run(connection, "downgrade")

    assert _constraint_names(connection) == {"policy_effect"}
