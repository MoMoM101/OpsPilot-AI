import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from opspilot_runner.config import RunnerSettings
from opspilot_runner.connectors.qdrant import QdrantConnector, QdrantConnectorError
from opspilot_runner.connectors.rag import RagBusinessHealthConnector
from opspilot_runner.connectors.sqlite import SQLiteConnector, SQLiteConnectorError
from opspilot_runner.registry import ConnectorRegistry
from opspilot_runner.target_policy import ProbeTargetPolicy


@pytest.mark.asyncio
async def test_sqlite_connector_is_read_only_and_reports_integrity(tmp_path: Path) -> None:
    database = tmp_path / "rag.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")
        connection.execute("INSERT INTO documents(content) VALUES ('local test data')")
    connector = SQLiteConnector([tmp_path])

    health = await connector.execute("sqlite.health", {"path": str(database)}, 10)
    integrity = await connector.execute("sqlite.integrity_check", {"path": str(database)}, 10)

    assert json.loads(health.output)["schemaObjectCount"] == 1
    assert json.loads(integrity.output)["healthy"] is True
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_sqlite_connector_reports_exclusive_lock(tmp_path: Path) -> None:
    database = tmp_path / "locked.db"
    with sqlite3.connect(database) as setup:
        setup.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
    blocker = sqlite3.connect(database, timeout=0)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        result = await SQLiteConnector([tmp_path]).execute(
            "sqlite.lock_status", {"path": str(database)}, 10
        )
    finally:
        blocker.rollback()
        blocker.close()

    payload = json.loads(result.output)
    assert payload["locked"] is True
    assert payload["errorType"] == "database_locked"


@pytest.mark.asyncio
async def test_sqlite_connector_rejects_path_outside_allowlist(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    database = outside / "rag.db"
    database.touch()

    with pytest.raises(SQLiteConnectorError) as error:
        await SQLiteConnector([allowed]).execute("sqlite.health", {"path": str(database)}, 10)

    assert error.value.code == "SQLITE_PATH_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_qdrant_connector_normalizes_collection_count_and_smoke_query() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/points/count"):
            assert json.loads(request.content) == {"exact": True}
            return httpx.Response(200, json={"result": {"count": 42}, "status": "ok"})
        if request.url.path.endswith("/points/query"):
            body = json.loads(request.content)
            assert body["query"] == [0.1, 0.2]
            assert body["with_payload"] is False
            return httpx.Response(
                200,
                json={"result": {"points": [{"id": 1}, {"id": 2}]}, "status": "ok"},
            )
        raise AssertionError(f"unexpected Qdrant path: {request.url.path}")

    connector = QdrantConnector(
        ProbeTargetPolicy(["qdrant"], [6333]),
        transport=httpx.MockTransport(handler),
    )
    count = await connector.execute(
        "qdrant.point_count",
        {"baseUrl": "http://qdrant:6333", "collection": "documents"},
        10,
    )
    query = await connector.execute(
        "qdrant.query_smoke",
        {
            "baseUrl": "http://qdrant:6333",
            "collection": "documents",
            "vector": [0.1, 0.2],
            "limit": 2,
        },
        10,
    )

    assert json.loads(count.output)["count"] == 42
    assert json.loads(query.output)["resultCount"] == 2
    assert "id" not in query.output


@pytest.mark.asyncio
async def test_qdrant_connector_rejects_unallowlisted_target() -> None:
    connector = QdrantConnector(ProbeTargetPolicy(["qdrant"], [6333]))

    with pytest.raises(QdrantConnectorError) as error:
        await connector.execute("qdrant.health", {"baseUrl": "http://external.example:6333"}, 10)

    assert error.value.code == "QDRANT_TARGET_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_rag_business_health_uses_fixed_contract_and_redacts_answer() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert json.loads(request.content) == {"question": "What is OpsPilot?"}
        return httpx.Response(
            200,
            json={"answer": "OpsPilot is the test system token=do-not-expose"},
        )

    connector = RagBusinessHealthConnector(
        ProbeTargetPolicy(["rag-api"], [8000]),
        transport=httpx.MockTransport(handler),
    )
    result = await connector.execute(
        "rag.business_health",
        {
            "url": "http://rag-api:8000/api/ask",
            "question": "What is OpsPilot?",
            "expectedTerms": ["OpsPilot", "test system"],
        },
        10,
    )

    payload = json.loads(result.output)
    assert payload["healthy"] is True
    assert payload["matchedTermCount"] == 2
    assert "do-not-expose" not in result.output
    assert result.redacted is True


def test_registry_advertises_only_configured_lab_connectors(tmp_path: Path) -> None:
    disabled = ConnectorRegistry(RunnerSettings())
    enabled = ConnectorRegistry(
        RunnerSettings(
            sqlite_allowed_roots=[tmp_path],
            probe_allowed_hosts=["qdrant", "rag-api"],
            probe_allowed_ports=[6333, 8000],
        )
    )

    disabled_names = {item["connector"] for item in disabled.capabilities()}
    enabled_names = {item["connector"] for item in enabled.capabilities()}
    assert {"sqlite", "qdrant", "rag"}.isdisjoint(disabled_names)
    assert {"sqlite", "qdrant", "rag"} <= enabled_names
