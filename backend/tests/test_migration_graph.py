from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_graph_has_one_current_head() -> None:
    backend = Path(__file__).resolve().parents[1]
    config = Config(backend / "alembic.ini")
    config.set_main_option("script_location", str(backend / "migrations"))

    assert ScriptDirectory.from_config(config).get_heads() == ["20260821_0037"]
