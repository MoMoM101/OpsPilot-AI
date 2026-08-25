from enum import StrEnum


class RunnerTaskStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunnerReadOperation(StrEnum):
    LIST_CONTAINERS = "docker.list_containers"
    INSPECT_CONTAINER = "docker.inspect_container"
    CONTAINER_LOGS = "docker.container_logs"
    CONTAINER_HEALTH = "docker.container_health"
    FILE_TAIL = "file.tail"
    JOURNAL_QUERY = "journal.query"
    HTTP_PROBE = "http.probe"
    TCP_PROBE = "tcp.probe"
    PROMETHEUS_QUERY = "prometheus.query"
    PROMETHEUS_QUERY_RANGE = "prometheus.query_range"
    HOST_SNAPSHOT = "host.snapshot"
    SQLITE_HEALTH = "sqlite.health"
    SQLITE_LOCK_STATUS = "sqlite.lock_status"
    SQLITE_INTEGRITY_CHECK = "sqlite.integrity_check"
    QDRANT_HEALTH = "qdrant.health"
    QDRANT_COLLECTION = "qdrant.collection"
    QDRANT_POINT_COUNT = "qdrant.point_count"
    QDRANT_QUERY_SMOKE = "qdrant.query_smoke"
    RAG_BUSINESS_HEALTH = "rag.business_health"
