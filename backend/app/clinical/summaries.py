"""Explicit, source-grounded plain-language study summaries with current-source caching."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from .database import ClinicalRepository
from .models import PlainLanguageSummaryPayload, Study

SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "1.0"


class SummaryError(RuntimeError):
    """Safe summary-generation failure without provider secrets or response bodies."""


class SummaryProvider(Protocol):
    name: str
    model: str

    async def summarize(self, study: Study) -> dict[str, Any]: ...


class DisabledSummaryProvider:
    name = "disabled"
    model = "disabled"

    async def summarize(self, study: Study) -> dict[str, Any]:
        raise SummaryError(
            f"LLM provider is disabled; no cached summary is available for {study.nct_id}"
        )


class OpenAISummaryProvider:
    """Minimal OpenAI-compatible adapter used only by the explicit maintenance CLI."""

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
            raise SummaryError("LLM_MODEL, LLM_API_KEY, and LLM_BASE_URL are required")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SummaryError("LLM_BASE_URL must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SummaryError("remote LLM_BASE_URL must use HTTPS to protect credentials")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = http_client

    async def summarize(self, study: Study) -> dict[str, Any]:
        if not study.source_description:
            raise SummaryError(f"{study.nct_id} has no official source description")
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "trialmatch_study_summary",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "nct_id": {"type": "string"},
                            "source_hash": {"type": "string"},
                            "plain_language_summary": {"type": "string"},
                        },
                        "required": ["nct_id", "source_hash", "plain_language_summary"],
                    },
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Rewrite only the supplied official study-purpose text in plain English. "
                        "Do not add eligibility conclusions, medical advice, probabilities, site facts, "
                        "or details absent from the source. Return the exact requested identifiers and "
                        "all JSON schema fields. Keep the summary under 1200 characters."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "nct_id": study.nct_id,
                            "source_hash": study.source_hash,
                            "title": study.title,
                            "official_source_description": study.source_description,
                            "source_url": study.source_url,
                        }
                    ),
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers
            )
            if response.status_code >= 400:
                raise SummaryError(f"OpenAI summary request failed with status {response.status_code}")
            envelope = response.json()
            choice = envelope["choices"][0]
            if choice.get("finish_reason") not in {None, "stop"}:
                raise SummaryError("OpenAI summary response was incomplete")
            message = choice["message"]
            if message.get("refusal"):
                raise SummaryError("OpenAI refused the summary request")
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError("provider content must be a JSON string")
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise TypeError("provider JSON must be an object")
            return payload
        except SummaryError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            safe = str(exc).replace(self.api_key, "[REDACTED]")[:300]
            raise SummaryError(
                f"OpenAI summary response failed validation: {type(exc).__name__}: {safe}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


def summary_provider_from_environment() -> SummaryProvider:
    provider = os.getenv("LLM_PROVIDER", "disabled").casefold()
    if provider == "disabled":
        return DisabledSummaryProvider()
    if provider == "openai-compatible":
        return OpenAISummaryProvider(
            model=os.getenv("LLM_MODEL", ""),
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", ""),
        )
    raise SummaryError(f"unsupported LLM_PROVIDER: {provider}")


class StudySummaryService:
    def __init__(self, repository: ClinicalRepository, provider: SummaryProvider):
        self.repository = repository
        self.provider = provider

    def cache_key(self, study: Study) -> str:
        material = ":".join(
            (
                study.nct_id,
                study.source_hash,
                SCHEMA_VERSION,
                PROMPT_VERSION,
                self.provider.name,
                self.provider.model,
            )
        )
        return hashlib.sha256(material.encode()).hexdigest()

    async def summarize(self, study: Study) -> tuple[PlainLanguageSummaryPayload, bool]:
        if not study.source_description:
            raise SummaryError(f"{study.nct_id} has no official source description")
        key = self.cache_key(study)
        cached = self.repository.get_cached_summary(key)
        if cached is not None:
            try:
                return self._validate(study, cached), True
            except SummaryError:
                pass
        raw = await self.provider.summarize(study)
        payload = self._validate(study, raw)
        self.repository.publish_summary(
            cache_key=key,
            nct_id=study.nct_id,
            source_hash=study.source_hash,
            provider=self.provider.name,
            model=self.provider.model,
            schema_version=SCHEMA_VERSION,
            prompt_version=PROMPT_VERSION,
            payload=payload.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
        return payload, False

    @staticmethod
    def _validate(study: Study, raw: dict[str, Any]) -> PlainLanguageSummaryPayload:
        try:
            payload = PlainLanguageSummaryPayload.model_validate_json(json.dumps(raw), strict=True)
        except ValidationError as exc:
            raise SummaryError(f"summary output failed schema validation: {exc.error_count()} error(s)") from exc
        if payload.nct_id != study.nct_id or payload.source_hash != study.source_hash:
            raise SummaryError("summary output identifiers do not match the current source record")
        return payload
