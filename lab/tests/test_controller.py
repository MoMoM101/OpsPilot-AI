from pathlib import Path

import httpx
import pytest

from opspilot_lab.controller import ControllerSettings, FaultController


def _controller(tmp_path: Path, requests: list[httpx.Request]) -> FaultController:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    return FaultController(
        ControllerSettings(sqlite_path=tmp_path / "rag.db"),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_qdrant_fault_is_replay_safe_and_cleanup_restores_proxy(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    controller = _controller(tmp_path, requests)

    injected = await controller.mutate("qdrant_down", "inject", "qdrant-inject-key")
    replayed = await controller.mutate("qdrant_down", "inject", "qdrant-inject-key")
    cleaned = await controller.mutate("qdrant_down", "cleanup", "qdrant-cleanup-key")

    assert injected["scenario"]["active"] is True
    assert replayed["replayed"] is True
    assert cleaned["scenario"]["active"] is False
    assert len(requests) == 2
    assert b'"enabled":false' in requests[0].content
    assert b'"enabled":true' in requests[1].content


@pytest.mark.asyncio
async def test_idempotency_key_cannot_be_reused_for_another_mutation(tmp_path: Path) -> None:
    controller = _controller(tmp_path, [])
    await controller.mutate("backend_500", "inject", "shared-mutation-key")

    with pytest.raises(ValueError, match="idempotency conflict"):
        await controller.mutate("backend_500", "cleanup", "shared-mutation-key")


@pytest.mark.asyncio
async def test_sqlite_lock_is_held_until_cleanup(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    database_path = tmp_path / "rag.db"
    database_path.touch()
    controller = _controller(tmp_path, requests)

    injected = await controller.mutate("sqlite_locked", "inject", "sqlite-inject-key")
    assert injected["scenario"]["active"] is True
    assert controller.sqlite_lock is not None

    cleaned = await controller.mutate("sqlite_locked", "cleanup", "sqlite-cleanup-key")
    assert cleaned["scenario"]["active"] is False
    assert controller.sqlite_lock is None
    assert requests == []


@pytest.mark.asyncio
async def test_collection_mismatch_deletes_and_restores_test_point(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    controller = _controller(tmp_path, requests)

    await controller.mutate("collection_count_mismatch", "inject", "collection-inject-key")
    await controller.mutate("collection_count_mismatch", "cleanup", "collection-cleanup-key")

    assert requests[0].url.path.endswith("/points/delete")
    assert requests[1].url.path.endswith("/points")
    assert b'"id":1' in requests[1].content
