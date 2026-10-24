"""Resilient asynchronous ClinicalTrials.gov API v2 client."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from .models import SourcePage, SourceStudy


DEFAULT_BASE_URL = "https://clinicaltrials.gov/api/v2"
LIST_FIELDS = (
    "NCTId,BriefTitle,OverallStatus,Condition,Phase,MinimumAge,MaximumAge,Sex,"
    "BriefSummary,DetailedDescription"
)


class ClinicalTrialsSourceError(RuntimeError):
    """A typed source failure safe to surface in provenance logs."""


class RepeatedPageTokenError(ClinicalTrialsSourceError):
    pass


class InvalidSourcePayloadError(ClinicalTrialsSourceError):
    pass


@dataclass(frozen=True)
class FetchResult:
    records: list[dict[str, Any]]
    page_count: int
    duplicate_identifier_count: int


@dataclass(frozen=True)
class PartialFetchError(ClinicalTrialsSourceError):
    message: str
    records: list[dict[str, Any]]
    page_count: int
    duplicate_identifier_count: int

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class DetailResult:
    record: dict[str, Any]
    retrieved_at: datetime
    from_cache: bool


class ClinicalTrialsClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        cache_dir: str | Path | None = None,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.base_url = (base_url or os.getenv("CLINICALTRIALS_API_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("CLINICALTRIALS_REQUEST_TIMEOUT_SECONDS", "6")
        )
        self.max_retries = max_retries if max_retries is not None else int(
            os.getenv("CLINICALTRIALS_MAX_RETRIES", "1")
        )
        self.cache_dir = Path(
            cache_dir or os.getenv("CLINICALTRIALS_CACHE_DIR", "backend/data/cache/clinicaltrials")
        )
        self._client = http_client
        self._owns_client = http_client is None
        self._sleep = sleep

    async def __aenter__(self) -> ClinicalTrialsClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("ClinicalTrialsClient must be used as an async context manager")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(url, params=params, timeout=self.timeout_seconds)
                if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"transient source status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {
                    408,
                    425,
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                if not retryable or attempt >= self.max_retries:
                    break
                await self._sleep(min(2**attempt, 8))
        raise ClinicalTrialsSourceError(f"ClinicalTrials.gov request failed: {last_error}") from last_error

    async def fetch_all_recruiting_massachusetts(self, page_size: int = 1000) -> FetchResult:
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_hashes: dict[str, str] = {}
        seen_tokens: set[str] = set()
        duplicate_count = 0
        page_count = 0
        token: str | None = None
        while True:
            params = self.list_parameters(page_size)
            if token:
                params["pageToken"] = token
            try:
                response = await self._get(f"{self.base_url}/studies", params=params)
                envelope = SourcePage.model_validate(response.json())
            except (ClinicalTrialsSourceError, ValueError, ValidationError) as exc:
                raise PartialFetchError(
                    message=str(exc),
                    records=records,
                    page_count=page_count,
                    duplicate_identifier_count=duplicate_count,
                ) from exc
            page_count += 1
            for record in envelope.studies:
                nct_id = (
                    record.get("protocolSection", {})
                    .get("identificationModule", {})
                    .get("nctId")
                )
                if nct_id:
                    canonical_hash = hashlib.sha256(
                        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                    if nct_id in seen_ids:
                        duplicate_count += 1
                        if seen_hashes[nct_id] != canonical_hash:
                            raise PartialFetchError(
                                message=f"conflicting duplicate source record for {nct_id}",
                                records=records,
                                page_count=page_count,
                                duplicate_identifier_count=duplicate_count,
                            )
                        continue
                    seen_ids.add(nct_id)
                    seen_hashes[nct_id] = canonical_hash
                records.append(record)
            next_token = envelope.next_page_token
            if not next_token:
                return FetchResult(records, page_count, duplicate_count)
            if next_token in seen_tokens:
                raise PartialFetchError(
                    message=f"ClinicalTrials.gov repeated page token after page {page_count}",
                    records=records,
                    page_count=page_count,
                    duplicate_identifier_count=duplicate_count,
                )
            seen_tokens.add(next_token)
            token = next_token

    def list_parameters(self, page_size: int) -> dict[str, Any]:
        return {
            "query.locn": "Massachusetts",
            "filter.overallStatus": "RECRUITING",
            "pageSize": page_size,
            "fields": LIST_FIELDS,
            "format": "json",
        }

    def list_query_url(self, page_size: int) -> str:
        return str(httpx.URL(f"{self.base_url}/studies", params=self.list_parameters(page_size)))

    @staticmethod
    def _validate_detail(record: dict[str, Any], requested_nct_id: str) -> None:
        try:
            parsed = SourceStudy.model_validate(record)
        except ValidationError as exc:
            raise InvalidSourcePayloadError(
                f"invalid detail payload for {requested_nct_id}: {exc}"
            ) from exc
        received_nct_id = parsed.protocol.identification.nct_id
        if received_nct_id != requested_nct_id:
            raise InvalidSourcePayloadError(
                f"detail identifier mismatch: requested {requested_nct_id}, received {received_nct_id}"
            )
        if not parsed.protocol.identification.brief_title or not parsed.protocol.identification.brief_title.strip():
            raise InvalidSourcePayloadError(
                f"detail {requested_nct_id} is missing required BriefTitle"
            )
        status = parsed.protocol.status.overall_status
        if not status or not status.strip():
            raise InvalidSourcePayloadError(
                f"detail {requested_nct_id} is missing required OverallStatus"
            )

    async def fetch_detail(self, nct_id: str, *, use_cache: bool = True) -> DetailResult:
        if not nct_id.startswith("NCT") or len(nct_id) != 11 or not nct_id[3:].isdigit():
            raise ValueError(f"invalid NCT identifier: {nct_id}")
        cache_path = self.cache_dir / f"{nct_id}.json"
        if use_cache and cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text())
                record = payload["study"]
                if not isinstance(record, dict):
                    raise TypeError("cached study must be an object")
                self._validate_detail(record, nct_id)
                return DetailResult(
                    record=record,
                    retrieved_at=datetime.fromisoformat(payload["retrieved_at"]),
                    from_cache=True,
                )
            except (
                KeyError,
                TypeError,
                ValueError,
                ValidationError,
                InvalidSourcePayloadError,
                json.JSONDecodeError,
            ):
                cache_path.unlink(missing_ok=True)

        response = await self._get(f"{self.base_url}/studies/{nct_id}")
        try:
            record = response.json()
            if not isinstance(record, dict):
                raise TypeError("detail response must be an object")
            self._validate_detail(record, nct_id)
        except (ValueError, TypeError, InvalidSourcePayloadError) as exc:
            raise InvalidSourcePayloadError(f"invalid detail payload for {nct_id}: {exc}") from exc
        retrieved_at = datetime.now(UTC)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "retrieved_at": retrieved_at.isoformat(),
            "source_url": f"{self.base_url}/studies/{nct_id}",
            "study": record,
        }
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True))
        temporary.replace(cache_path)
        return DetailResult(record=record, retrieved_at=retrieved_at, from_cache=False)
