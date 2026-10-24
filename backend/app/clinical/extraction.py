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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .database import ClinicalRepository
from .models import CriterionOperator, ExtractionPayload, StructuredCriterion, Study


SCHEMA_VERSION = "2.1"
PROMPT_VERSION = "2.1"


class ExtractionError(RuntimeError):
    pass


class ProviderUnavailable(ExtractionError):
    pass


class InvalidExtraction(ExtractionError):
    def __init__(self, message: str, feedback: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.feedback = feedback or []


class TokenUsage(BaseModel):
    """Sanitized token counters from one provider request."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


_UNSUPPORTED_PROVIDER_SCHEMA_KEYS = {
    "default",
    "title",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
}


def openai_strict_schema() -> dict[str, Any]:
    """Convert Pydantic JSON Schema to OpenAI's strict supported subset."""

    schema = ExtractionPayload.model_json_schema()

    def normalize(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                normalize(item)
            return
        if not isinstance(node, dict):
            return
        for key in _UNSUPPORTED_PROVIDER_SCHEMA_KEYS:
            node.pop(key, None)
        properties = node.get("properties")
        if isinstance(properties, dict):
            node["required"] = list(properties)
            node["additionalProperties"] = False
        for value in node.values():
            normalize(value)

    normalize(schema)
    return schema


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
        self.last_usage: TokenUsage | None = None

    async def extract(self, study: Study) -> dict[str, Any]:
        self.last_usage = None
        return await self._request(study)

    async def repair(
        self,
        study: Study,
        invalid_payload: dict[str, Any],
        feedback: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Perform one bounded structured repair using sanitized validator feedback."""

        return await self._request(
            study,
            repair_context={"invalid_payload": invalid_payload, "validation_errors": feedback},
        )

    async def _request(
        self,
        study: Study,
        repair_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
                    "schema": openai_strict_schema(),
                },
            },
            "messages": self._messages(study, repair_context),
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers
            )
            if response.status_code >= 400:
                raise self._sanitized_http_error(response)
            envelope = response.json()
            usage = envelope.get("usage")
            if isinstance(usage, dict):
                request_usage = TokenUsage.model_validate(usage)
                if self.last_usage is None:
                    self.last_usage = request_usage
                else:
                    self.last_usage = TokenUsage(
                        prompt_tokens=self.last_usage.prompt_tokens + request_usage.prompt_tokens,
                        completion_tokens=(
                            self.last_usage.completion_tokens + request_usage.completion_tokens
                        ),
                        total_tokens=self.last_usage.total_tokens + request_usage.total_tokens,
                    )
            choice = envelope["choices"][0]
            finish_reason = choice.get("finish_reason")
            message = choice["message"]
            if message.get("refusal"):
                raise ProviderUnavailable("OpenAI refused the structured extraction request")
            if finish_reason not in {None, "stop"}:
                raise ProviderUnavailable(
                    f"OpenAI structured extraction ended with finish_reason={finish_reason!r}"
                )
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError("provider message content must be a JSON string")
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise TypeError("provider JSON must be an object")
            return payload
        except ProviderUnavailable:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            safe_message = str(exc).replace(self.api_key, "[REDACTED]")
            raise ProviderUnavailable(
                f"LLM provider response failed validation: {type(exc).__name__}: {safe_message[:500]}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()

    def _messages(
        self,
        study: Study,
        repair_context: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        system_prompt = (
            "Extract structured eligibility rules without deciding eligibility. Account for every "
            "provided source_item_id and copy original_text verbatim. Use uncovered_items when an "
            "item is not processed. Return every schema property; use null for inapplicable scalar "
            "fields and [] for children/uncovered_items. Valid predicate combinations: "
            "age_years uses equals/not_equals/greater_than/greater_than_or_equal/less_than/"
            "less_than_or_equal with numeric value, or between with lower+upper; target is null. "
            "sex uses equals/not_equals with string value; target is null. condition, medication, "
            "and procedure use only present/absent/within_days and require target; value, bounds, "
            "and unit are null; within_days also requires temporal_window_days. laboratory_value "
            "uses a numeric comparison, requires target and unit. all/any compounds use attribute "
            "unsupported as a container, null scalar fields, and at least two valid children. If a "
            "clinical concept cannot be represented safely, use attribute=unsupported and "
            "operator=unsupported with all scalar fields null and children=[]. Invalid: condition "
            "+ equals; condition + present with target=null; condition name placed in value; all/any "
            "with condition children lacking targets. Never guess a target, unit, duration, or fact."
        )
        source = {
            "nct_id": study.nct_id,
            "source_url": study.source_url,
            "eligibility_criteria": study.eligibility_criteria,
            "source_items": [
                {"source_item_id": item_id, "original_text": text}
                for item_id, (text, _) in _protocol_items(
                    study.eligibility_criteria or ""
                ).items()
            ],
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(source)},
        ]
        if repair_context is not None:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Repair the prior structured output using only these sanitized Pydantic "
                        "validation errors. Preserve every source_item_id and verbatim original_text. "
                        "Replace any unsafe or unrepresentable predicate with the explicit unsupported "
                        "predicate; do not guess.\n"
                        + json.dumps(repair_context)
                    ),
                }
            )
        return messages

    def _sanitized_http_error(self, response: httpx.Response) -> ProviderUnavailable:
        error_type: str | None = None
        error_code: str | None = None
        error_param: str | None = None
        message = "Request rejected by provider."
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                error_type = _safe_error_value(error.get("type"))
                error_code = _safe_error_value(error.get("code"))
                error_param = _safe_error_value(error.get("param"))
                message = _safe_error_value(error.get("message")) or message
        except (ValueError, TypeError):
            pass
        message = message.replace(self.api_key, "[REDACTED]")[:800]
        return ProviderUnavailable(
            "OpenAI API request failed "
            f"(status={response.status_code}, type={error_type}, code={error_code}, "
            f"param={error_param}): {message}"
        )


def _safe_error_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)[:800]
    return None


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
            try:
                payload = self._validate_payload(study, raw_payload)
            except InvalidExtraction as first_error:
                repair = getattr(self.provider, "repair", None)
                if not callable(repair) or not first_error.feedback:
                    raise
                repaired_payload = await repair(study, raw_payload, first_error.feedback)
                payload = self._validate_payload(study, repaired_payload)
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
            feedback = [
                {
                    "path": ".".join(str(part) for part in error["loc"]),
                    "type": str(error["type"]),
                    "message": str(error["msg"])[:300],
                }
                for error in exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )[:20]
            ]
            raise InvalidExtraction(
                "provider output failed schema validation: " + json.dumps(feedback),
                feedback=feedback,
            ) from exc
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
                message = (
                    "multi-clause source items require an explicit compound or unsupported predicate"
                )
                candidate_index = payload.criteria.index(candidate)
                feedback = [
                    {
                        "path": f"criteria.{candidate_index}.predicate",
                        "type": "value_error.multi_clause_representation",
                        "message": message,
                    }
                ]
                raise InvalidExtraction(message, feedback=feedback)
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
