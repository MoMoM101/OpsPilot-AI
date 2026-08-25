import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from opspilot_lab.security import require_lab_token


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSPILOT_LAB_RAG_", extra="ignore")

    sqlite_path: Path = Path("/lab/data/rag.db")
    embedding_url: str = "http://embedding:8001"
    qdrant_url: str = "http://qdrant-proxy:16333"
    collection: str = "documents"
    dependency_timeout_seconds: float = 3


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class FaultRequest(BaseModel):
    enabled: bool


settings = RagSettings()
_backend_500_enabled = False


def _initialize_sqlite() -> None:
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.sqlite_path) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, content TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO documents(id, content) VALUES (1, ?)",
            ("OpsPilot is a local AIOps fault-lab document.",),
        )


async def _initialize_qdrant() -> None:
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        await client.put(
            f"{settings.qdrant_url}/collections/{settings.collection}",
            json={"vectors": {"size": 4, "distance": "Cosine"}},
        )
        await client.put(
            f"{settings.qdrant_url}/collections/{settings.collection}/points",
            json={
                "points": [
                    {
                        "id": 1,
                        "vector": [0.1, 0.2, 0.3, 0.4],
                        "payload": {"documentId": 1},
                    }
                ]
            },
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _initialize_sqlite()
    with suppress(httpx.HTTPError):
        await _initialize_qdrant()
    yield


app = FastAPI(title="OpsPilot RAG Fault Lab", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"alive": True}


@app.get("/ready")
async def ready() -> dict[str, bool]:
    sqlite_ready = False
    qdrant_ready = False
    try:
        with sqlite3.connect(
            f"{settings.sqlite_path.as_uri()}?mode=ro", uri=True, timeout=0.1
        ) as db:
            sqlite_ready = db.execute("SELECT 1").fetchone() == (1,)
    except sqlite3.Error:
        pass
    try:
        async with httpx.AsyncClient(
            timeout=settings.dependency_timeout_seconds, trust_env=False
        ) as client:
            response = await client.get(f"{settings.qdrant_url}/readyz")
            qdrant_ready = response.status_code == 200
    except httpx.HTTPError:
        pass
    return {"ready": sqlite_ready and qdrant_ready, "sqlite": sqlite_ready, "qdrant": qdrant_ready}


@app.post("/api/ask")
async def ask(body: AskRequest) -> dict[str, object]:
    if _backend_500_enabled:
        raise HTTPException(status_code=500, detail="injected backend failure")
    try:
        async with httpx.AsyncClient(
            timeout=settings.dependency_timeout_seconds, trust_env=False
        ) as client:
            embedding = await client.post(
                f"{settings.embedding_url}/embed", json={"text": body.question}
            )
            embedding.raise_for_status()
            vector = embedding.json()["vector"]
            query = await client.post(
                f"{settings.qdrant_url}/collections/{settings.collection}/points/query",
                json={
                    "query": vector,
                    "limit": 3,
                    "with_payload": True,
                    "with_vector": False,
                },
            )
            query.raise_for_status()
    except (httpx.HTTPError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="RAG dependency unavailable") from exc
    try:
        with sqlite3.connect(
            f"{settings.sqlite_path.as_uri()}?mode=ro", uri=True, timeout=0.1
        ) as db:
            row = db.execute("SELECT content FROM documents WHERE id = 1").fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="SQLite unavailable") from exc
    if row is None:
        raise HTTPException(status_code=503, detail="Lab document missing")
    points = query.json().get("result", {}).get("points", [])
    return {
        "answer": str(row[0]),
        "retrievedPointCount": len(points) if isinstance(points, list) else 0,
    }


@app.put("/internal/faults/backend-500", dependencies=[Depends(require_lab_token)])
async def set_backend_500(body: FaultRequest) -> dict[str, bool]:
    global _backend_500_enabled
    _backend_500_enabled = body.enabled
    return {"enabled": _backend_500_enabled}
