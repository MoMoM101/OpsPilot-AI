from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260821_0037_incident_event_cursor.py"
    )
    spec = importlib.util.spec_from_file_location("incident_event_cursor_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_event_cursor_migration_backfills_historical_outbox_sequences() -> None:
    connection = sa.create_engine("sqlite://").connect()
    connection.execute(sa.text("CREATE TABLE incidents (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(
        sa.text(
            "CREATE TABLE outbox_events ("
            "sequence INTEGER PRIMARY KEY, incident_id VARCHAR(36) NOT NULL)"
        )
    )
    connection.execute(
        sa.text("INSERT INTO incidents (id) VALUES ('first'), ('second'), ('empty')")
    )
    connection.execute(
        sa.text(
            "INSERT INTO outbox_events (sequence, incident_id) VALUES "
            "(2, 'first'), (7, 'second'), (11, 'first')"
        )
    )
    module = _migration_module()
    module.op = Operations(MigrationContext.configure(connection))

    module.upgrade()

    rows = connection.execute(
        sa.text("SELECT id, event_cursor FROM incidents ORDER BY id")
    ).all()
    assert rows == [("empty", 0), ("first", 11), ("second", 7)]
    column = next(
        item for item in sa.inspect(connection).get_columns("incidents")
        if item["name"] == "event_cursor"
    )
    assert column["nullable"] is False


def test_event_cursor_migration_downgrade_removes_column() -> None:
    connection = sa.create_engine("sqlite://").connect()
    connection.execute(sa.text("CREATE TABLE incidents (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(
        sa.text(
            "CREATE TABLE outbox_events ("
            "sequence INTEGER PRIMARY KEY, incident_id VARCHAR(36) NOT NULL)"
        )
    )
    module = _migration_module()
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()

    module.downgrade()

    assert {item["name"] for item in sa.inspect(connection).get_columns("incidents")} == {
        "id"
    }
