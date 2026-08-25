from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa


class _MigrationOp:
    def __init__(self, connection: sa.Connection) -> None:
        self.connection = connection
        self.created_constraints: list[tuple[str, str, tuple[str, ...]]] = []

    def get_bind(self) -> sa.Connection:
        return self.connection

    def create_unique_constraint(self, name: str, table: str, columns: list[str]) -> None:
        self.created_constraints.append((name, table, tuple(columns)))


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260814_0030_action_authorization_consumption.py"
    )
    spec = importlib.util.spec_from_file_location("action_authorization_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _connection() -> sa.Connection:
    engine = sa.create_engine("sqlite://")
    connection = engine.connect()
    connection.execute(
        sa.text(
            """
            CREATE TABLE action_requests (
                id TEXT PRIMARY KEY,
                policy_decision_id TEXT NOT NULL,
                approval_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
    )
    return connection


def _run_upgrade(module: ModuleType, migration_op: _MigrationOp) -> None:
    module.op = migration_op
    upgrade: Any = module.upgrade
    upgrade()


def test_upgrade_reports_historical_authorization_duplicates_before_constraints() -> None:
    connection = _connection()
    connection.execute(
        sa.text(
            """
            INSERT INTO action_requests (id, policy_decision_id, approval_id, created_at) VALUES
            ('action-old', 'policy-1', 'approval-1', '2026-01-01T00:00:00Z'),
            ('action-new', 'policy-1', 'approval-1', '2026-01-02T00:00:00Z')
            """
        )
    )
    migration_op = _MigrationOp(connection)

    with pytest.raises(RuntimeError) as exc_info:
        _run_upgrade(_migration_module(), migration_op)

    message = str(exc_info.value)
    assert "policy_decision_id=policy-1" in message
    assert "approval_id=approval-1" in message
    assert "keep=action-old" in message
    assert "remove=['action-new']" in message
    assert migration_op.created_constraints == []


def test_upgrade_adds_constraints_after_historical_duplicates_are_cleaned() -> None:
    connection = _connection()
    connection.execute(
        sa.text(
            """
            INSERT INTO action_requests (id, policy_decision_id, approval_id, created_at) VALUES
            ('action-old', 'policy-1', 'approval-1', '2026-01-01T00:00:00Z'),
            ('action-other', 'policy-2', NULL, '2026-01-02T00:00:00Z')
            """
        )
    )
    migration_op = _MigrationOp(connection)

    _run_upgrade(_migration_module(), migration_op)

    assert migration_op.created_constraints == [
        ("uq_action_requests_policy_decision_id", "action_requests", ("policy_decision_id",)),
        ("uq_action_requests_approval_id", "action_requests", ("approval_id",)),
    ]
