"""Runtime configuration and FastAPI dependencies for Clinical Intelligence."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .database import ClinicalRepository


@lru_cache(maxsize=1)
def get_repository() -> ClinicalRepository:
    database_url = os.getenv(
        "TRIALMATCH_DATABASE_URL", "sqlite:///./backend/data/trialmatch.sqlite3"
    )
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("Clinical Intelligence currently supports only sqlite:/// database URLs")
    value = database_url.removeprefix(prefix)
    if not value:
        raise RuntimeError("SQLite database path cannot be empty")
    return ClinicalRepository(Path(value))
