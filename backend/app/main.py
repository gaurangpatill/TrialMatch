"""Shared FastAPI composition root.

Feature routers are intentionally not implemented on the shared scaffold branch.
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Stable health contract for the shared application process."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["trialmatch-api"] = "trialmatch-api"
    version: str


app = FastAPI(
    title="TrialMatch API",
    description="Shared API scaffold for the TrialMatch research-access prototype.",
    version="0.1.0",
)


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Report that the API process is responsive."""

    return HealthResponse(version=app.version)
