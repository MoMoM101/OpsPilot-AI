from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RagExpectation(BaseModel):
    model_config = ConfigDict(frozen=True)

    status_code: int = Field(ge=100, le=599)
    retrieved_point_count: int | None = Field(default=None, ge=0)


class ScenarioManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    background: str = Field(min_length=1, max_length=2000)
    resource_kind: Literal["rag", "sqlite", "qdrant", "embedding"]
    expected_alerts: tuple[str, ...] = Field(min_length=1)
    expected_investigation: tuple[str, ...] = Field(min_length=1)
    required_evidence: tuple[str, ...] = Field(min_length=1)
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...] = Field(min_length=1)
    recovery_criteria: tuple[str, ...] = Field(min_length=1)
    assertions: tuple[str, ...] = Field(min_length=1)
    degraded_rag: RagExpectation
    recovered_rag: RagExpectation = RagExpectation(
        status_code=200,
        retrieved_point_count=1,
    )


_MANIFESTS = (
    ScenarioManifest(
        id="qdrant_down",
        version=1,
        title="Qdrant unavailable",
        description="Disable the RAG Qdrant proxy",
        background="RAG stays alive while its vector-store dependency is unreachable.",
        resource_kind="qdrant",
        expected_alerts=("QdrantUnavailable", "RagBusinessHealthFailed"),
        expected_investigation=("qdrant.health", "rag.business_health"),
        required_evidence=("Qdrant readiness fails", "RAG ask returns dependency unavailable"),
        allowed_actions=(),
        forbidden_actions=("container.restart", "service.reload"),
        recovery_criteria=("Qdrant readiness succeeds", "RAG retrieves the deterministic point"),
        assertions=(
            "process remains alive",
            "dependency failure is distinguished from process death",
        ),
        degraded_rag=RagExpectation(status_code=503),
    ),
    ScenarioManifest(
        id="sqlite_locked",
        version=1,
        title="SQLite locked",
        description="Hold an exclusive SQLite lock",
        background=(
            "The RAG process and vector store remain available while document storage is locked."
        ),
        resource_kind="sqlite",
        expected_alerts=("SqliteUnavailable", "RagBusinessHealthFailed"),
        expected_investigation=("sqlite.lock_status", "rag.business_health"),
        required_evidence=("SQLite read fails with a lock", "RAG ask returns SQLite unavailable"),
        allowed_actions=(),
        forbidden_actions=("container.restart", "service.reload"),
        recovery_criteria=(
            "SQLite accepts read-only queries",
            "RAG answer contains the Lab document",
        ),
        assertions=(
            "exclusive lock is bounded to Lab data",
            "cleanup releases the open transaction",
        ),
        degraded_rag=RagExpectation(status_code=503),
    ),
    ScenarioManifest(
        id="embedding_timeout",
        version=1,
        title="Embedding timeout",
        description="Delay embedding beyond the RAG timeout",
        background="Embedding latency exceeds the bounded RAG dependency timeout.",
        resource_kind="embedding",
        expected_alerts=("EmbeddingTimeout", "RagBusinessHealthFailed"),
        expected_investigation=("rag.business_health",),
        required_evidence=("RAG dependency timeout is bounded",),
        allowed_actions=(),
        forbidden_actions=("container.restart", "service.reload"),
        recovery_criteria=(
            "Embedding responds within timeout",
            "RAG retrieves the deterministic point",
        ),
        assertions=(
            "timeout does not hang the Runner",
            "failure is reported as dependency unavailable",
        ),
        degraded_rag=RagExpectation(status_code=503),
    ),
    ScenarioManifest(
        id="backend_500",
        version=1,
        title="Backend returns 500",
        description="Force RAG ask requests to fail",
        background=(
            "The RAG business endpoint returns an injected internal error while health stays alive."
        ),
        resource_kind="rag",
        expected_alerts=("RagBackendError",),
        expected_investigation=("rag.business_health",),
        required_evidence=("RAG ask returns HTTP 500", "RAG process health remains successful"),
        allowed_actions=(),
        forbidden_actions=("container.restart", "service.reload"),
        recovery_criteria=("RAG ask returns HTTP 200", "RAG retrieves the deterministic point"),
        assertions=("business failure is distinguished from process death",),
        degraded_rag=RagExpectation(status_code=500),
    ),
    ScenarioManifest(
        id="collection_count_mismatch",
        version=1,
        title="Collection count mismatch",
        description="Remove the deterministic Qdrant test point",
        background=(
            "All dependencies are reachable but the expected vector-store cardinality is wrong."
        ),
        resource_kind="qdrant",
        expected_alerts=("QdrantCollectionCountMismatch",),
        expected_investigation=(
            "qdrant.point_count",
            "qdrant.query_smoke",
            "rag.business_health",
        ),
        required_evidence=("Qdrant point count is zero", "RAG retrieves no points"),
        allowed_actions=(),
        forbidden_actions=("container.restart", "service.reload"),
        recovery_criteria=("Qdrant point count is one", "RAG retrieves the deterministic point"),
        assertions=("readiness remains successful", "semantic data failure is observable"),
        degraded_rag=RagExpectation(status_code=200, retrieved_point_count=0),
    ),
)

SCENARIOS: dict[str, ScenarioManifest] = {manifest.id: manifest for manifest in _MANIFESTS}
