import asyncio
import random
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from app.core.logging import get_logger
from app.core.worker_health import WorkerHealthRegistry
from app.storage.database import Database
from app.storage.models import OutboxEventRecord
from app.storage.repositories import OutboxRepository

logger = get_logger(__name__)


class OutboxSink(Protocol):
    async def publish(self, event: OutboxEventRecord) -> None: ...

    async def close(self) -> None: ...


class StructuredLogOutboxSink:
    async def publish(self, event: OutboxEventRecord) -> None:
        logger.info("outbox_event_published", **_event_payload(event))

    async def close(self) -> None:
        return None


class WebhookOutboxSink:
    def __init__(self, url: str, token: str | None, timeout_seconds: float) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self.url = url
        self.client = httpx.AsyncClient(timeout=timeout_seconds, headers=headers)

    async def publish(self, event: OutboxEventRecord) -> None:
        try:
            response = await self.client.post(
                self.url,
                json=_event_payload(event),
                headers={"Idempotency-Key": str(event.event_id)},
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise RetryableOutboxError(str(exc)) from exc
        if response.is_success:
            return
        message = f"Webhook returned HTTP {response.status_code}"
        if response.status_code >= 500 or response.status_code in {408, 409, 425, 429}:
            raise RetryableOutboxError(message, response.status_code)
        raise PermanentOutboxError(message, response.status_code)

    async def close(self) -> None:
        await self.client.aclose()


class OutboxPublishError(RuntimeError):
    def __init__(self, failed: int) -> None:
        super().__init__(f"Failed to publish {failed} Outbox event(s)")
        self.failed = failed


class OutboxDeliveryError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RetryableOutboxError(OutboxDeliveryError):
    pass


class PermanentOutboxError(OutboxDeliveryError):
    pass


class OutboxPublisher:
    def __init__(
        self,
        database: Database,
        sink: OutboxSink,
        *,
        batch_size: int,
        retention_days: int,
        max_attempts: int = 10,
        retry_base_seconds: float = 2,
        retry_max_seconds: float = 300,
    ) -> None:
        self.database = database
        self.sink = sink
        self.batch_size = batch_size
        self.retention = timedelta(days=retention_days)
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds

    async def run_once(self) -> tuple[int, int]:
        published = 0
        failed = 0
        now = datetime.now(UTC)
        async with self.database.session_factory() as session:
            repository = OutboxRepository(session)
            events = await repository.pending_for_publish(self.batch_size, now)
            for event in events:
                event.publish_attempts += 1
                try:
                    await self.sink.publish(event)
                except Exception as exc:
                    failed += 1
                    permanent = isinstance(exc, PermanentOutboxError)
                    exhausted = event.publish_attempts >= self.max_attempts
                    event.last_error = str(exc)[:1000]
                    event.last_status_code = (
                        exc.status_code if isinstance(exc, OutboxDeliveryError) else None
                    )
                    if permanent or exhausted:
                        event.dead_lettered_at = now
                        event.next_attempt_at = None
                    else:
                        event.next_attempt_at = now + timedelta(
                            seconds=self._retry_delay(event.publish_attempts)
                        )
                    logger.warning(
                        "outbox_event_publish_failed",
                        event_id=str(event.event_id),
                        sequence=event.sequence,
                        attempt=event.publish_attempts,
                        error_type=type(exc).__name__,
                        dead_lettered=permanent or exhausted,
                        next_attempt_at=(
                            event.next_attempt_at.isoformat()
                            if event.next_attempt_at is not None
                            else None
                        ),
                    )
                else:
                    event.published_at = now
                    event.next_attempt_at = None
                    event.last_error = None
                    event.last_status_code = None
                    published += 1
            deleted = await repository.delete_published_before(
                now - self.retention,
                self.batch_size,
            )
            await session.commit()
        if failed:
            raise OutboxPublishError(failed)
        return published, deleted

    def _retry_delay(self, attempt: int) -> float:
        ceiling = min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2 ** max(0, attempt - 1)),
        )
        return random.uniform(0, ceiling)


async def run_outbox_publisher(
    publisher: OutboxPublisher,
    interval_seconds: float,
    health: WorkerHealthRegistry | None = None,
) -> None:
    worker_name = "outbox_publisher"
    try:
        while True:
            try:
                result = (
                    await health.run_monitored(worker_name, publisher.run_once())
                    if health is not None
                    else await publisher.run_once()
                )
                if health is not None:
                    health.success(worker_name)
                published, deleted = result
                if published or deleted:
                    logger.info(
                        "outbox_batch_completed",
                        published=published,
                        deleted=deleted,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if health is not None:
                    health.failure(worker_name, exc)
                logger.error("outbox_publisher_failed", error_type=type(exc).__name__)
            await asyncio.sleep(interval_seconds)
    finally:
        await publisher.sink.close()


def _event_payload(event: OutboxEventRecord) -> dict[str, object]:
    return {
        "eventId": str(event.event_id),
        "sequence": event.sequence,
        "type": event.event_type,
        "aggregateType": event.aggregate_type,
        "aggregateId": str(event.aggregate_id),
        "incidentId": str(event.incident_id),
        "traceId": str(event.trace_id),
        "version": event.aggregate_version,
        "occurredAt": event.occurred_at.isoformat(),
        "payload": event.payload,
    }
