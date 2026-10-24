"""Strict eligibility extraction boundary with cache and configurable provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from .database import ClinicalRepository
from .models import CriterionOperator, ExtractionPayload, StructuredCriterion, Study


SCHEMA_VERSION = "2.0"
PROMPT_VERSION = "2.0"


class ExtractionError(RuntimeError):
    pass


class ProviderUnavailable(ExtractionError):
    pass


class InvalidExtraction(ExtractionError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    async def extract(self, study: Study) -> dict[str, Any]: ...


class DisabledProvider:
    name = "disabled"
    model = "disabled"

    async def extract(self, study: Study) -> dict[str, Any]:
        raise ProviderUnavailable(
            f"LLM provider is disabled; no cached extraction is available for {study.nct_id}"
        )


class OpenAICompatibleProvider:
    """Minimal schema-guided adapter for OpenAI-compatible chat completion APIs."""

    name = "openai-compatible"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 60,
        http_client: httpx.AsyncClient | None = None,
    ):
        if not model or not api_key or not base_url:
            raise ProviderUnavailable("LLM_MODEL, LLM_API_KEY, and LLM_BASE_URL are required")
        parsed_url = urlparse(base_url)
        loopback_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ProviderUnavailable("LLM_BASE_URL must be an absolute HTTP(S) URL")
        if parsed_url.scheme != "https" and parsed_url.hostname not in loopback_hosts:
            raise ProviderUnavailable("remote LLM_BASE_URL must use HTTPS to protect credentials")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = http_client

    async def extract(self, study: Study) -> dict[str, Any]:
        if not study.eligibility_criteria:
            raise ExtractionError(f"{study.nct_id} has no detailed eligibility text")
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "trialmatch_eligibility",
                    "strict": True,
                    "schema": ExtractionPayload.model_json_schema(),
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Segment and account for every atomic inclusion or exclusion protocol item. "
                        "Copy every original_text verbatim. Put representable and unsupported items "
                        "in criteria; put unprocessed items in coverage.uncovered_items with a reason. "
                        "Declare complete only when every protocol item is accounted for and none is "
                        "uncovered. Do not decide patient eligibility or invent criteria."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "nct_id": study.nct_id,
                            "source_url": study.source_url,
                            "eligibility_criteria": study.eligibility_criteria,
                            "source_items": [
                                {"source_item_id": item_id, "original_text": text}
                                for item_id, (text, _) in _protocol_items(
                                    study.eligibility_criteria
                                ).items()
                            ],
                        }
                    ),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            response.raise_for_status()
            envelope = response.json()
            content = envelope["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("provider message content must be a JSON string")
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise TypeError("provider JSON must be an object")
            return payload
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"LLM provider request failed: {type(exc).__name__}: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()


def _protocol_items(eligibility_text: str) -> dict[str, tuple[str, int]]:
    """Segment non-heading lines and identify obvious atomic-clause counts."""

    items: dict[str, tuple[str, int]] = {}
    for raw_line in eligibility_text.splitlines():
        line = raw_line.strip()
        if not line or (line.endswith(":") and len(line) <= 120):
            continue
        item_id = f"item-{len(items) + 1:03d}"
        items[item_id] = (line, _obvious_clause_count(line))
    return items


def _obvious_clause_count(text: str) -> int:
    normalized = re.sub(
        r"(?i)\bbetween\s+\d+(?:\.\d+)?\s+and\s+\d+(?:\.\d+)?",
        "range_expression",
        text,
    )
    normalized = re.sub(
        r"(?i)\bor\s+(?:older|younger|less|more)\b",
        "comparative_expression",
        normalized,
    )
    separators = len(re.findall(r"\s+(?:and|or)\s+|;", normalized, flags=re.IGNORECASE))
    return separators + 1


def provider_from_environment() -> LLMProvider:
    provider = os.getenv("LLM_PROVIDER", "disabled").casefold()
    if provider == "disabled":
        return DisabledProvider()
    if provider == "openai-compatible":
        return OpenAICompatibleProvider(
            model=os.getenv("LLM_MODEL", ""),
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", ""),
        )
    raise ProviderUnavailable(f"unsupported LLM_PROVIDER: {provider}")


class EligibilityExtractor:
    def __init__(self, repository: ClinicalRepository, provider: LLMProvider):
        self.repository = repository
        self.provider = provider

    def cache_key(self, study: Study) -> str:
        value = ":".join(
            [
                study.nct_id,
                study.source_hash,
                SCHEMA_VERSION,
                PROMPT_VERSION,
                self.provider.name,
                self.provider.model,
            ]
        )
        return hashlib.sha256(value.encode()).hexdigest()

    async def extract(self, study: Study) -> tuple[list[StructuredCriterion], bool]:
        if not study.eligibility_criteria:
            raise ExtractionError(f"{study.nct_id} has no detailed eligibility text")
        key = self.cache_key(study)
        try:
            cached = self.repository.get_cached_extraction(key)
        except (json.JSONDecodeError, TypeError):
            self.repository.delete_extraction_cache(key)
            cached = None
        if cached is not None:
            try:
                payload = self._validate_payload(study, cached)
                criteria = self._materialize(study, payload)
                self._publish(study, key, payload, criteria)
                return criteria, True
            except InvalidExtraction:
                self.repository.delete_extraction_cache(key)

        try:
            raw_payload = await self.provider.extract(study)
            payload = self._validate_payload(study, raw_payload)
            criteria = self._materialize(study, payload)
            self._publish(study, key, payload, criteria)
            return criteria, False
        except ExtractionError as exc:
            self.repository.record_extraction_attempt(
                nct_id=study.nct_id,
                source_hash=study.source_hash,
                provider=self.provider.name,
                model=self.provider.model,
                schema_version=SCHEMA_VERSION,
                prompt_version=PROMPT_VERSION,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                created_at=datetime.now(UTC),
            )
            raise
        except Exception as exc:
            wrapped = ExtractionError(f"extraction publication failed: {type(exc).__name__}: {exc}")
            self.repository.record_extraction_attempt(
                nct_id=study.nct_id,
                source_hash=study.source_hash,
                provider=self.provider.name,
                model=self.provider.model,
                schema_version=SCHEMA_VERSION,
                prompt_version=PROMPT_VERSION,
                status="failed",
                error=str(wrapped),
                created_at=datetime.now(UTC),
            )
            raise wrapped from exc

    def _publish(
        self,
        study: Study,
        cache_key: str,
        payload: ExtractionPayload,
        criteria: list[StructuredCriterion],
    ) -> None:
        now = datetime.now(UTC)
        self.repository.publish_extraction(
            cache_key=cache_key,
            nct_id=study.nct_id,
            source_hash=study.source_hash,
            provider=self.provider.name,
            model=self.provider.model,
            schema_version=SCHEMA_VERSION,
            prompt_version=PROMPT_VERSION,
            payload=payload.model_dump(mode="json"),
            criteria=criteria,
            created_at=now,
        )

    @staticmethod
    def _validate_payload(study: Study, raw_payload: dict[str, Any]) -> ExtractionPayload:
        try:
            # Validate through JSON mode: provider values are JSON primitives, while
            # strict Python mode would incorrectly require pre-built Enum instances.
            payload = ExtractionPayload.model_validate_json(
                json.dumps(raw_payload), strict=True
            )
        except ValidationError as exc:
            raise InvalidExtraction(f"provider output failed schema validation: {exc}") from exc
        if payload.nct_id != study.nct_id:
            raise InvalidExtraction(
                f"provider NCT identifier mismatch: expected {study.nct_id}, got {payload.nct_id}"
            )
        assert study.eligibility_criteria is not None
        protocol_items = _protocol_items(study.eligibility_criteria)
        if payload.coverage.protocol_item_count != len(protocol_items):
            raise InvalidExtraction(
                "coverage protocol_item_count does not match deterministic source segmentation"
            )
        candidates = {item.source_item_id: item for item in payload.criteria}
        gaps = {item.source_item_id: item for item in payload.coverage.uncovered_items}
        if set(candidates) | set(gaps) != set(protocol_items):
            raise InvalidExtraction(
                "coverage source_item_id values must account for every segmented source item"
            )
        for item_id, (source_text, clause_count) in protocol_items.items():
            submitted = candidates.get(item_id) or gaps[item_id]
            if submitted.original_text != source_text:
                raise InvalidExtraction(
                    "coverage evidence is not verbatim source evidence for its source_item_id"
                )
            candidate = candidates.get(item_id)
            if (
                payload.coverage.status == "complete"
                and candidate is not None
                and clause_count > 1
                and candidate.predicate.operator != CriterionOperator.UNSUPPORTED
                and (
                    candidate.predicate.operator
                    not in {CriterionOperator.ALL, CriterionOperator.ANY}
                    or len(candidate.predicate.children) < clause_count
                )
            ):
                raise InvalidExtraction(
                    "multi-clause source items require an explicit compound or unsupported predicate"
                )
        return payload

    def _materialize(
        self,
        study: Study,
        payload: ExtractionPayload,
        *,
        created_at: datetime | None = None,
    ) -> list[StructuredCriterion]:
        timestamp = created_at or datetime.now(UTC)
        result: list[StructuredCriterion] = []
        for index, candidate in enumerate(payload.criteria, start=1):
            identity = hashlib.sha256(
                (
                    f"{study.nct_id}:{candidate.source_item_id}:{index}:"
                    f"{candidate.classification.value}:"
                    f"{candidate.original_text}:{candidate.predicate.model_dump_json()}"
                ).encode()
            ).hexdigest()[:12]
            result.append(
                StructuredCriterion(
                    criterion_id=f"{study.nct_id}-llm-{identity}",
                    source_item_id=candidate.source_item_id,
                    nct_id=study.nct_id,
                    classification=candidate.classification,
                    original_text=candidate.original_text,
                    predicate=candidate.predicate,
                    source_url=study.source_url,
                    extraction_uncertainty=candidate.uncertainty,
                    extraction_method="llm",
                    schema_version=SCHEMA_VERSION,
                    provider=self.provider.name,
                    model=self.provider.model,
                    source_hash=study.source_hash,
                    created_at=timestamp,
                )
            )
        return result
