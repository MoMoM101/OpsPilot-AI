import asyncio
import hashlib

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from opspilot_lab.security import require_lab_token

app = FastAPI(title="OpsPilot Lab Embedding Mock")
_timeout_enabled = False


class EmbedRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class FaultRequest(BaseModel):
    enabled: bool


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"healthy": True}


@app.post("/embed")
async def embed(body: EmbedRequest) -> dict[str, list[float]]:
    if _timeout_enabled:
        await asyncio.sleep(30)
    digest = hashlib.sha256(body.text.encode()).digest()
    vector = [round((digest[index] / 255) * 2 - 1, 6) for index in range(4)]
    return {"vector": vector}


@app.put("/internal/faults/timeout", dependencies=[Depends(require_lab_token)])
async def set_timeout(body: FaultRequest) -> dict[str, bool]:
    global _timeout_enabled
    _timeout_enabled = body.enabled
    return {"enabled": _timeout_enabled}
