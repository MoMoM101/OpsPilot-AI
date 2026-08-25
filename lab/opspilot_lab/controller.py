import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from opspilot_lab.scenarios import SCENARIOS, ScenarioManifest
from opspilot_lab.security import require_lab_token


class ControllerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSPILOT_LAB_CONTROLLER_", extra="ignore")

    toxiproxy_url: str = "http://toxiproxy:8474"
    qdrant_upstream: str = "qdrant:6333"
    qdrant_listen: str = "0.0.0.0:16333"
    qdrant_url: str = "http://qdrant:6333"
    rag_url: str = "http://rag-api:8000"
    embedding_url: str = "http://embedding:8001"
    sqlite_path: Path = Path("/lab/data/rag.db")
    collection: str = "documents"


class MutationRequest(BaseModel):
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=128)


class FaultController:
    def __init__(
        self,
        settings: ControllerSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.active: set[str] = set()
        self.replays: dict[str, tuple[str, str, dict[str, Any]]] = {}
        self.sqlite_lock: sqlite3.Connection | None = None
        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        last_error: Exception | None = None
        for _attempt in range(30):
            try:
                await self._ensure_proxy()
                await self._set_proxy(True)
                await self._remote_fault(self.settings.rag_url, "backend-500", False)
                await self._remote_fault(self.settings.embedding_url, "timeout", False)
                await self._ensure_collection()
                await self._restore_point()
                return
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                await asyncio.sleep(0.5)
        raise RuntimeError("Fault Lab dependencies did not become ready") from last_error

    def scenarios(self) -> list[dict[str, Any]]:
        return [self._scenario(item) for item in SCENARIOS.values()]

    async def mutate(
        self, scenario_id: str, action: Literal["inject", "cleanup"], idempotency_key: str
    ) -> dict[str, Any]:
        definition = SCENARIOS.get(scenario_id)
        if definition is None:
            raise KeyError(scenario_id)
        async with self.lock:
            existing = self.replays.get(idempotency_key)
            if existing is not None:
                if existing[0:2] != (scenario_id, action):
                    raise ValueError("idempotency conflict")
                return {**existing[2], "replayed": True}
            if action == "inject":
                await self._inject(scenario_id)
                self.active.add(scenario_id)
            else:
                await self._cleanup(scenario_id)
                self.active.discard(scenario_id)
            response = {"scenario": self._scenario(definition), "replayed": False}
            self.replays[idempotency_key] = (scenario_id, action, response)
            return response

    def _scenario(self, definition: ScenarioManifest) -> dict[str, Any]:
        active = definition.id in self.active
        return {
            "id": definition.id,
            "title": definition.title,
            "description": definition.description,
            "status": "active" if active else "ready",
            "version": definition.version,
            "active": active,
            "supported": True,
        }

    async def _inject(self, scenario_id: str) -> None:
        if scenario_id == "qdrant_down":
            await self._set_proxy(False)
        elif scenario_id == "sqlite_locked":
            if self.sqlite_lock is None:
                connection = sqlite3.connect(
                    self.settings.sqlite_path, timeout=0, check_same_thread=False
                )
                connection.execute("BEGIN EXCLUSIVE")
                self.sqlite_lock = connection
        elif scenario_id == "embedding_timeout":
            await self._remote_fault(self.settings.embedding_url, "timeout", True)
        elif scenario_id == "backend_500":
            await self._remote_fault(self.settings.rag_url, "backend-500", True)
        else:
            await self._delete_point()

    async def _cleanup(self, scenario_id: str) -> None:
        if scenario_id == "qdrant_down":
            await self._set_proxy(True)
        elif scenario_id == "sqlite_locked":
            if self.sqlite_lock is not None:
                self.sqlite_lock.rollback()
                self.sqlite_lock.close()
                self.sqlite_lock = None
        elif scenario_id == "embedding_timeout":
            await self._remote_fault(self.settings.embedding_url, "timeout", False)
        elif scenario_id == "backend_500":
            await self._remote_fault(self.settings.rag_url, "backend-500", False)
        else:
            await self._restore_point()

    async def _ensure_proxy(self) -> None:
        response = await self._request(
            "POST",
            f"{self.settings.toxiproxy_url}/proxies",
            {
                "name": "qdrant",
                "listen": self.settings.qdrant_listen,
                "upstream": self.settings.qdrant_upstream,
                "enabled": True,
            },
        )
        if response.status_code not in {200, 201, 409}:
            response.raise_for_status()

    async def _set_proxy(self, enabled: bool) -> None:
        response = await self._request(
            "POST",
            f"{self.settings.toxiproxy_url}/proxies/qdrant",
            {
                "name": "qdrant",
                "listen": self.settings.qdrant_listen,
                "upstream": self.settings.qdrant_upstream,
                "enabled": enabled,
            },
        )
        response.raise_for_status()

    async def _remote_fault(self, base_url: str, fault: str, enabled: bool) -> None:
        response = await self._request(
            "PUT",
            f"{base_url}/internal/faults/{fault}",
            {"enabled": enabled},
            authenticated=True,
        )
        response.raise_for_status()

    async def _delete_point(self) -> None:
        response = await self._request(
            "POST",
            f"{self.settings.qdrant_url}/collections/{self.settings.collection}/points/delete",
            {"points": [1]},
        )
        response.raise_for_status()

    async def _ensure_collection(self) -> None:
        response = await self._request(
            "PUT",
            f"{self.settings.qdrant_url}/collections/{self.settings.collection}",
            {"vectors": {"size": 4, "distance": "Cosine"}},
        )
        if response.status_code not in {200, 201, 409}:
            response.raise_for_status()

    async def _restore_point(self) -> None:
        response = await self._request(
            "PUT",
            f"{self.settings.qdrant_url}/collections/{self.settings.collection}/points",
            {
                "points": [
                    {
                        "id": 1,
                        "vector": [0.1, 0.2, 0.3, 0.4],
                        "payload": {"documentId": 1},
                    }
                ]
            },
        )
        response.raise_for_status()

    async def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any],
        *,
        authenticated: bool = False,
    ) -> httpx.Response:
        headers = {"X-OpsPilot-Lab-Token": LabToken.value()} if authenticated else None
        async with httpx.AsyncClient(
            transport=self.transport, timeout=10, trust_env=False, follow_redirects=False
        ) as client:
            return await client.request(method, url, json=body, headers=headers)


class LabToken:
    @staticmethod
    def value() -> str:
        from opspilot_lab.security import LabSettings

        return LabSettings().token


settings = ControllerSettings()
controller = FaultController(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await controller.initialize()
    yield
    if controller.sqlite_lock is not None:
        controller.sqlite_lock.rollback()
        controller.sqlite_lock.close()


app = FastAPI(title="OpsPilot Fault Lab Controller", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"healthy": True}


@app.get("/scenarios", dependencies=[Depends(require_lab_token)])
async def list_scenarios() -> list[dict[str, Any]]:
    return controller.scenarios()


@app.post("/scenarios/{scenario_id}/{action}", dependencies=[Depends(require_lab_token)])
async def mutate_scenario(
    scenario_id: str, action: Literal["inject", "cleanup"], body: MutationRequest
) -> dict[str, Any]:
    try:
        return await controller.mutate(scenario_id, action, body.idempotency_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="idempotency conflict") from exc
