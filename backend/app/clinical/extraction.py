"""Strict eligibility extraction boundary with cache and configurable provider."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from .database import ClinicalRepository
from .models import ExtractionPayload, StructuredCriterion, Study


SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "1.0"


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
                        "Extract only criteria representable by the supplied schema. Copy original_text "
                        "verbatim from the protocol. Use unsupported when meaning cannot be represented. "
                        "Do not decide patient eligibility and do not invent criteria."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "nct_id": study.nct_id,
                            "source_url": study.source_url,
                            "eligibility_criteria": study.eligibility_criteria,
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
        cached = self.repository.get_cached_extraction(key)
        if cached is not None:
            payload = self._validate_payload(study, cached)
            criteria = self._materialize(study, payload)
            self.repository.replace_criteria(study.nct_id, "llm", criteria)
            return criteria, True

        raw_payload = await self.provider.extract(study)
        payload = self._validate_payload(study, raw_payload)
        now = datetime.now(UTC)
        self.repository.save_extraction_cache(
            cache_key=key,
            nct_id=study.nct_id,
            source_hash=study.source_hash,
            provider=self.provider.name,
            model=self.provider.model,
            payload=payload.model_dump(mode="json"),
            created_at=now,
        )
        criteria = self._materialize(study, payload, created_at=now)
        self.repository.replace_criteria(study.nct_id, "llm", criteria)
        return criteria, False

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
        for candidate in payload.criteria:
            if candidate.original_text not in study.eligibility_criteria:
                raise InvalidExtraction("criterion original_text is not verbatim source evidence")
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
                    f"{study.nct_id}:{index}:{candidate.classification.value}:"
                    f"{candidate.original_text}:{candidate.predicate.model_dump_json()}"
                ).encode()
            ).hexdigest()[:12]
            result.append(
                StructuredCriterion(
                    criterion_id=f"{study.nct_id}-llm-{identity}",
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
