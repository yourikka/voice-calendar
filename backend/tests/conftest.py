from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database, get_connection
from app.main import app


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    previous_preload = os.environ.get("VOICE_ASR_PRELOAD_ON_STARTUP")
    os.environ["VOICE_ASR_PRELOAD_ON_STARTUP"] = "false"
    db_path = tmp_path / "test.db"
    settings = Settings(database_path=db_path)
    Database(settings).initialize()

    def override_connection() -> Iterator:
        with Database(settings).connect() as conn:
            yield conn

    app.dependency_overrides[get_connection] = override_connection
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    if previous_preload is None:
        os.environ.pop("VOICE_ASR_PRELOAD_ON_STARTUP", None)
    else:
        os.environ["VOICE_ASR_PRELOAD_ON_STARTUP"] = previous_preload
