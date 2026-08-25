import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.application import create_app
from app.core.config import Settings
from app.services.outbox import (
    OutboxPublisher,
    OutboxPublishError,
    PermanentOutboxError,
    RetryableOutboxError,
    WebhookOutboxSink,
)
from app.storage import Base
from app.storage.models import OutboxEventRecord
from app.storage.repositories import OutboxRepository


class RecordingSink:
    def __init__(self, fail_once: UUID | None = None) -> None:
        self.fail_once = fail_once
        self.failed = False
        self.event_ids: list[UUID] = []

    async def publish(self, event: OutboxEventRecord) -> None:
        self.event_ids.append(event.event_id)
        if event.event_id == self.fail_once and not self.failed:
            self.failed = True
            raise RuntimeError("temporary sink failure")

    async def close(self) -> None:
        return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            database_readiness_enabled=False,
        )
    )

    async def create_schema() -> None:
        async with app.state.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(app) as test_client:
        yield test_client


def _create_incident(client: TestClient) -> dict[str, object]:
    environment = client.post(
        "/api/v1/environments",
        json={"name": "Outbox Test", "slug": "outbox-test"},
    ).json()
    resource = client.post(
        "/api/v1/resources",
        json={
            "environmentId": environment["id"],
            "name": "outbox-resource",
            "kind": "service",
            "criticality": "medium",
        },
    ).json()
    response = client.post(
        "/api/v1/incidents",
        json={
            "title": "Verify Outbox delivery",
            "severity": "medium",
            "resourceId": resource["id"],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_outbox_retries_failed_event_with_stable_id_and_preserves_sse(
    client: TestClient,
) -> None:
    incident = _create_incident(client)
    database = client.app.state.database

    async def scenario() -> tuple[UUID, int]:
        async with database.session_factory() as session:
            pending = await OutboxRepository(session).pending_for_publish(100)
            first_id = pending[0].event_id

        sink = RecordingSink(fail_once=first_id)
        publisher = OutboxPublisher(database, sink, batch_size=100, retention_days=7)
        with pytest.raises(OutboxPublishError):
            await publisher.run_once()

        async with database.session_factory() as session:
            after_failure = await OutboxRepository(session).get_by_event_id(
                first_id, for_update=True
            )
            assert after_failure is not None
            assert after_failure.publish_attempts == 1
            assert after_failure.next_attempt_at is not None
            after_failure.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        published, deleted = await publisher.run_once()
        assert (published, deleted) == (1, 0)
        async with database.session_factory() as session:
            remaining = await OutboxRepository(session).pending_for_publish(100)
            assert remaining == []
        return first_id, sink.event_ids.count(first_id)

    first_id, attempts = asyncio.run(scenario())

    assert attempts == 2
    stream = client.get(
        f"/api/v1/incidents/{incident['id']}/stream",
        params={"follow": False},
    )
    assert stream.status_code == 200
    assert str(first_id) in stream.text


def test_outbox_retention_deletes_only_old_published_events(client: TestClient) -> None:
    _create_incident(client)
    database = client.app.state.database

    async def scenario() -> tuple[int, int, int]:
        sink = RecordingSink()
        publisher = OutboxPublisher(database, sink, batch_size=100, retention_days=1)
        await publisher.run_once()
        async with database.session_factory() as session:
            events = await OutboxRepository(session).pending_for_publish(100)
            assert events == []
            stored = list(await session.scalars(select(OutboxEventRecord)))
            for event in stored:
                event.published_at = datetime.now(UTC) - timedelta(days=2)
            count = len(stored)
            await session.commit()

        published, deleted = await publisher.run_once()
        async with database.session_factory() as session:
            remaining = int(
                await session.scalar(select(func.count()).select_from(OutboxEventRecord)) or 0
            )
        assert deleted == count
        return published, deleted, remaining

    published, deleted, remaining = asyncio.run(scenario())
    assert published == 0
    assert deleted > 0
    assert remaining == 0


def test_webhook_mode_requires_a_url() -> None:
    with pytest.raises(ValueError, match="Outbox webhook URL"):
        Settings(outbox_publisher_mode="webhook")


def test_permanent_failure_enters_dead_letter_and_admin_can_replay(
    client: TestClient,
) -> None:
    _create_incident(client)
    database = client.app.state.database

    class PermanentFailureSink(RecordingSink):
        async def publish(self, event: OutboxEventRecord) -> None:
            raise PermanentOutboxError("Webhook returned HTTP 400", 400)

    async def publish() -> UUID:
        async with database.session_factory() as session:
            event = (await OutboxRepository(session).pending_for_publish(100))[0]
            event_id = event.event_id
        publisher = OutboxPublisher(
            database,
            PermanentFailureSink(),
            batch_size=100,
            retention_days=7,
        )
        with pytest.raises(OutboxPublishError):
            await publisher.run_once()
        return event_id

    event_id = asyncio.run(publish())
    status = client.get("/api/v1/outbox/status")
    assert status.status_code == 200
    assert status.json()["deadLetterCount"] == 1
    dead_letter_response = client.get("/api/v1/outbox/dead-letters?limit=1&offset=0")
    assert dead_letter_response.headers["X-Total-Count"] == "1"
    assert dead_letter_response.headers["X-Limit"] == "1"
    assert dead_letter_response.headers["X-Offset"] == "0"
    dead_letters = dead_letter_response.json()
    target = next(item for item in dead_letters if item["eventId"] == str(event_id))
    assert target["lastStatusCode"] == 400

    replay = client.post(f"/api/v1/outbox/dead-letters/{event_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["status"] == "pending"
    assert client.get("/api/v1/outbox/status").json()["deadLetterCount"] == 0


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(400, PermanentOutboxError), (429, RetryableOutboxError), (503, RetryableOutboxError)],
)
def test_webhook_classifies_http_failures(
    status_code: int,
    error_type: type[Exception],
) -> None:
    event = OutboxEventRecord(
        sequence=1,
        event_id=uuid4(),
        event_type="incident.created",
        aggregate_type="incident",
        aggregate_id=uuid4(),
        incident_id=uuid4(),
        trace_id=uuid4(),
        aggregate_version=1,
        payload={},
        occurred_at=datetime.now(UTC),
        publish_attempts=0,
    )

    async def scenario() -> None:
        sink = WebhookOutboxSink("https://events.example.test", None, 1)
        await sink.client.aclose()
        sink.client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(status_code, text="failure")
            )
        )
        with pytest.raises(error_type):
            await sink.publish(event)
        await sink.close()

    asyncio.run(scenario())


def test_retryable_failure_moves_to_dead_letter_after_max_attempts(
    client: TestClient,
) -> None:
    _create_incident(client)
    database = client.app.state.database

    class AlwaysFailingSink(RecordingSink):
        async def publish(self, event: OutboxEventRecord) -> None:
            raise RetryableOutboxError("temporary unavailable", 503)

    async def scenario() -> tuple[int, int | None]:
        async with database.session_factory() as session:
            event_id = (await OutboxRepository(session).pending_for_publish(100))[0].event_id
        publisher = OutboxPublisher(
            database,
            AlwaysFailingSink(),
            batch_size=100,
            retention_days=7,
            max_attempts=2,
            retry_base_seconds=1,
            retry_max_seconds=1,
        )
        with pytest.raises(OutboxPublishError):
            await publisher.run_once()
        async with database.session_factory() as session:
            event = await OutboxRepository(session).get_by_event_id(event_id, for_update=True)
            assert event is not None
            assert event.dead_lettered_at is None
            event.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        with pytest.raises(OutboxPublishError):
            await publisher.run_once()
        async with database.session_factory() as session:
            event = await OutboxRepository(session).get_by_event_id(event_id)
            assert event is not None
            assert event.dead_lettered_at is not None
            return event.publish_attempts, event.last_status_code

    assert asyncio.run(scenario()) == (2, 503)
