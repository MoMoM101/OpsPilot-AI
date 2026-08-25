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
        / "20260821_0036_demo_installations.py"
    )
    spec = importlib.util.spec_from_file_location("demo_installation_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_installation_migration_seeds_inactive_singleton() -> None:
    connection = sa.create_engine("sqlite://").connect()
    connection.execute(sa.text("CREATE TABLE environments (id CHAR(32) PRIMARY KEY)"))
    module = _migration_module()
    module.op = Operations(MigrationContext.configure(connection))

    module.upgrade()

    row = connection.execute(
        sa.text(
            "SELECT key, manifest_version, generation, environment_id, active "
            "FROM demo_installations"
        )
    ).one()
    assert tuple(row) == ("guided_tour", 1, 0, None, 0)
