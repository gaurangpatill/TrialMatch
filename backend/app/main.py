"""Shared FastAPI composition root with coordinated clinical router registration."""

import uuid
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.app.clinical.models import ErrorBody, ErrorDetail, ErrorResponse
from backend.app.clinical.router import router as clinical_router


class HealthResponse(BaseModel):
    """Stable health contract for the shared application process."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["trialmatch-api"] = "trialmatch-api"
    version: str


app = FastAPI(
    title="TrialMatch API",
    description="Source-grounded TrialMatch research-access prototype API.",
    version="0.2.0",
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return the coordinated error envelope for request-shape failures."""

    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error["loc"] if part not in {"body", "query"}) or None,
            reason=error["msg"],
        )
        for error in exc.errors()
    ]
    payload = ErrorResponse(
        error=ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            details=details,
            retryable=False,
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=422, content=payload.model_dump(mode="json"))


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Report that the API process is responsive."""

    return HealthResponse(version=app.version)


app.include_router(clinical_router)
