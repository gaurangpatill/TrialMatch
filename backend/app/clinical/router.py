"""Clinical Intelligence HTTP endpoints."""

from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from .database import ClinicalRepository
from .dependencies import get_repository
from .matching import MatchingService, UnknownTrialIds
from .models import (
    DataFreshness,
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
    MatchRequest,
    MatchResponse,
    Pagination,
    StudySummary,
    SyntheticPatient,
    TrialSearchResponse,
)


router = APIRouter(prefix="/api", tags=["clinical"])
RepositoryDependency = Annotated[ClinicalRepository, Depends(get_repository)]


@router.get("/trials", response_model=TrialSearchResponse)
def search_trials(
    repository: RepositoryDependency,
    query: Annotated[str | None, Query(max_length=200)] = None,
    condition: str | None = None,
    phase: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TrialSearchResponse:
    cleaned_query = query.strip() if query and query.strip() else None
    studies, total = repository.search_studies(
        query=cleaned_query,
        condition=condition,
        phase=phase,
        page=page,
        page_size=page_size,
    )
    return TrialSearchResponse(
        items=[
            StudySummary(
                nct_id=study.nct_id,
                title=study.title,
                overall_status=study.overall_status,
                conditions=study.conditions,
                phases=study.phases,
                minimum_age=study.minimum_age,
                maximum_age=study.maximum_age,
                sex=study.sex,
                locations=study.locations,
                source_url=study.source_url,
                retrieved_at=study.retrieved_at,
            )
            for study in studies
        ],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        ),
        data_freshness=DataFreshness(retrieved_at=repository.latest_retrieved_at()),
    )


@router.post(
    "/match",
    response_model=MatchResponse,
    responses={400: {"model": ErrorResponse}},
)
def match_trials(
    request: MatchRequest,
    repository: RepositoryDependency,
) -> MatchResponse | JSONResponse:
    if request.patient.synthetic is not True:
        request_id = uuid.uuid4().hex
        error = ErrorResponse(
            error=ErrorBody(
                code="SYNTHETIC_PROFILE_REQUIRED",
                message="Only explicitly synthetic profiles are accepted.",
                details=[ErrorDetail(field="patient.synthetic", reason="must equal true")],
                retryable=False,
                request_id=request_id,
            )
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))
    patient = SyntheticPatient.model_validate(request.patient.model_dump())
    try:
        return MatchingService(repository).match(
            patient,
            trial_ids=request.trial_ids,
            limit=request.limit,
        )
    except UnknownTrialIds as exc:
        error = ErrorResponse(
            error=ErrorBody(
                code="TRIALS_NOT_FOUND",
                message="One or more requested trials are not present in the local source snapshot.",
                details=[
                    ErrorDetail(field="trial_ids", reason=f"not found: {identifier}")
                    for identifier in exc.identifiers
                ],
                retryable=False,
                request_id=uuid.uuid4().hex,
            )
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))
