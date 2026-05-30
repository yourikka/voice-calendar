from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.db import initialize_database
from app.services.asr import ASRService


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    initialize_database(settings)
    asr = ASRService(settings)
    if settings.asr_preload_on_startup and asr.is_configured():
        asr.warmup_async()
    yield


app = FastAPI(title="Voice Calendar API", version="0.1.0", lifespan=lifespan)
app.include_router(router)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
