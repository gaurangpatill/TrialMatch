from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.app.clinical.database import ClinicalRepository
from backend.app.clinical.extraction import (
    EligibilityExtractor,
    InvalidExtraction,
    OpenAICompatibleProvider,
    ProviderUnavailable,
    openai_strict_schema,
)
from backend.app.clinical.models import Predicate


class FakeProvider:
    name = "fake-provider"
    model = "fake-model"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def extract(self, study):
        self.calls += 1
        return self.payload


class FailingSameIdentityProvider:
    name = "fake-provider"
    model = "fake-model"

    async def extract(self, study):
        raise ProviderUnavailable("provider unavailable")


def valid_payload(nct_id="NCT00000001"):
    return {
        "nct_id": nct_id,
        "coverage": {
            "status": "complete",
            "protocol_item_count": 1,
            "accounted_item_count": 1,
            "uncovered_items": [],
        },
        "criteria": [
            {
                "source_item_id": "item-001",
                "classification": "inclusion",
                "original_text": "Participants must be 18 years or older.",
                "predicate": {
                    "attribute": "age_years",
                    "operator": "greater_than_or_equal",
                    "value": 18,
                },
                "uncertainty": None,
            }
        ],
    }


@pytest.mark.asyncio
async def test_valid_extraction_preserves_exact_source_and_is_cached(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    provider = FakeProvider(valid_payload())
    extractor = EligibilityExtractor(repository, provider)

    criteria, from_cache = await extractor.extract(study)
    cached_criteria, cached = await extractor.extract(study)

    assert from_cache is False
    assert cached is True
    assert provider.calls == 1
    assert criteria[0].original_text == "Participants must be 18 years or older."
    assert criteria[0].source_url == study.source_url
    assert cached_criteria[0].criterion_id == criteria[0].criterion_id


@pytest.mark.asyncio
async def test_cached_extraction_survives_provider_unavailability(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    await EligibilityExtractor(repository, FakeProvider(valid_payload())).extract(study)

    criteria, cached = await EligibilityExtractor(
        repository, FailingSameIdentityProvider()
    ).extract(study)

    assert cached is True
    assert len(criteria) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda payload: payload.update({"unexpected": True}), "schema validation"),
        (lambda payload: payload.update({"nct_id": "NCT00000002"}), "identifier mismatch"),
        (
            lambda payload: payload["criteria"][0].update({"original_text": "Invented criterion"}),
            "not verbatim source evidence",
        ),
        (
            lambda payload: payload["criteria"][0]["predicate"].update(
                {"operator": "between", "lower": 65, "upper": 18}
            ),
            "schema validation",
        ),
    ],
)
async def test_invalid_structured_llm_response_is_rejected(
    mutate, match, study_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    payload = valid_payload()
    mutate(payload)

    with pytest.raises(InvalidExtraction, match=match):
        await EligibilityExtractor(repository, FakeProvider(payload)).extract(study)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "coverage",
    [
        {
            "status": "complete",
            "protocol_item_count": 2,
            "accounted_item_count": 1,
            "uncovered_items": [],
        },
        {
            "status": "partial",
            "protocol_item_count": 1,
            "accounted_item_count": 1,
            "uncovered_items": [],
        },
        {
            "status": "complete",
            "protocol_item_count": 2,
            "accounted_item_count": 1,
            "uncovered_items": [
                {"source_item_id": "item-002", "original_text": "Invented gap", "reason": "not parsed"}
            ],
        },
    ],
)
async def test_coverage_declaration_must_reconcile_and_preserve_source(
    coverage, study_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    payload = valid_payload()
    payload["coverage"] = coverage

    with pytest.raises(InvalidExtraction):
        await EligibilityExtractor(repository, FakeProvider(payload)).extract(study)


def openai_payload(nct_id="NCT00000001"):
    payload = valid_payload(nct_id)
    payload["criteria"][0]["predicate"] = {
        "attribute": "age_years",
        "operator": "greater_than_or_equal",
        "target": None,
        "value": 18,
        "lower": None,
        "upper": None,
        "include_lower": None,
        "include_upper": None,
        "unit": None,
        "temporal_window_days": None,
        "children": [],
    }
    return payload


def _walk_schema(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_schema(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_schema(value)


def test_openai_schema_uses_strict_supported_subset():
    schema = openai_strict_schema()
    unsupported = {
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
        "allOf",
        "not",
        "if",
        "then",
        "else",
        "dependentRequired",
        "dependentSchemas",
    }

    assert schema["type"] == "object"
    assert "$defs" in schema
    for node in _walk_schema(schema):
        assert not (set(node) & unsupported)
        if isinstance(node.get("properties"), dict):
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            assert reference.removeprefix("#/$defs/") in schema["$defs"]

    predicate = schema["$defs"]["Predicate"]
    assert set(predicate["required"]) == set(predicate["properties"])
    assert predicate["properties"]["children"]["items"]["$ref"] == "#/$defs/Predicate"
    assert "uncertainty" in schema["$defs"]["ExtractionCandidate"]["required"]
    assert "uncovered_items" in schema["$defs"]["ExtractionCoverageDeclaration"]["required"]


@pytest.mark.asyncio
async def test_openai_400_exposes_sanitized_schema_error_without_api_key(study_factory):
    secret = "test-secret-must-not-appear"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body["response_format"]["json_schema"]["schema"]
        assert set(schema["required"]) == set(schema["properties"])
        return httpx.Response(
            400,
            request=request,
            json={
                "error": {
                    "message": (
                        "Invalid schema for response_format: every property must be required; "
                        f"credential={secret}"
                    ),
                    "type": "invalid_request_error",
                    "param": "response_format",
                    "code": "invalid_json_schema",
                    "internal": {"diagnostic": "must not be emitted"},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            model="gpt-4.1-mini",
            api_key=secret,
            base_url="https://api.openai.test/v1",
            http_client=client,
        )
        with pytest.raises(ProviderUnavailable) as raised:
            await provider.extract(study_factory())

    message = str(raised.value)
    assert "status=400" in message
    assert "invalid_request_error" in message
    assert "invalid_json_schema" in message
    assert "response_format" in message
    assert "Invalid schema" in message
    assert secret not in message
    assert "internal" not in message
    assert "[REDACTED]" in message


@pytest.mark.asyncio
async def test_openai_structured_success_returns_payload_and_token_usage(study_factory):
    expected = openai_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1-mini"
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(expected), "refusal": None},
                    }
                ],
                "usage": {
                    "prompt_tokens": 321,
                    "completion_tokens": 123,
                    "total_tokens": 444,
                    "prompt_tokens_details": {"cached_tokens": 10},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            model="gpt-4.1-mini",
            api_key="test-key",
            base_url="https://api.openai.test/v1",
            http_client=client,
        )
        result = await provider.extract(study_factory())

    assert result == expected
    assert provider.last_usage is not None
    assert provider.last_usage.model_dump() == {
        "prompt_tokens": 321,
        "completion_tokens": 123,
        "total_tokens": 444,
    }


@pytest.mark.asyncio
async def test_openai_refusal_and_truncation_fail_closed(study_factory):
    responses = [
        {
            "choices": [
                {"finish_reason": "stop", "message": {"content": None, "refusal": "declined"}}
            ]
        },
        {
            "choices": [
                {"finish_reason": "length", "message": {"content": "{}", "refusal": None}}
            ]
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=responses.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            model="gpt-4.1-mini",
            api_key="test-key",
            base_url="https://api.openai.test/v1",
            http_client=client,
        )
        with pytest.raises(ProviderUnavailable, match="refused"):
            await provider.extract(study_factory())
        with pytest.raises(ProviderUnavailable, match="finish_reason"):
            await provider.extract(study_factory())


@pytest.mark.parametrize(
    "predicate,message",
    [
        (
            {
                "attribute": "condition",
                "operator": "equals",
                "target": "lung cancer",
                "value": "lung cancer",
            },
            "condition requires a fact operator",
        ),
        (
            {
                "attribute": "unsupported",
                "operator": "all",
                "children": [
                    {"attribute": "condition", "operator": "present"},
                    {"attribute": "age_years", "operator": "greater_than_or_equal", "value": 18},
                ],
            },
            "condition predicates require target",
        ),
        (
            {
                "attribute": "unsupported",
                "operator": "all",
                "children": [
                    {"attribute": "age_years", "operator": "greater_than_or_equal", "value": 18},
                    {"attribute": "condition", "operator": "absent"},
                ],
            },
            "condition predicates require target",
        ),
    ],
)
def test_real_openai_predicate_failures_remain_strict(predicate, message):
    with pytest.raises(PydanticValidationError, match=message):
        Predicate.model_validate(predicate)


@pytest.mark.asyncio
async def test_openai_validation_failure_gets_one_bounded_structured_repair(
    study_factory, tmp_path
):
    secret = "repair-test-secret"
    study = study_factory()
    invalid = openai_payload()
    invalid["criteria"][0]["predicate"] = {
        "attribute": "condition",
        "operator": "equals",
        "target": "synthetic condition",
        "value": "synthetic condition",
        "lower": None,
        "upper": None,
        "include_lower": None,
        "include_upper": None,
        "unit": None,
        "temporal_window_days": None,
        "children": [],
    }
    repaired = openai_payload()
    repaired["criteria"][0]["predicate"] = {
        "attribute": "unsupported",
        "operator": "unsupported",
        "target": None,
        "value": None,
        "lower": None,
        "upper": None,
        "include_lower": None,
        "include_upper": None,
        "unit": None,
        "temporal_window_days": None,
        "children": [],
    }
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        content = invalid if len(requests) == 1 else repaired
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(content), "refusal": None},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )

    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    repository.upsert_studies([study])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            model="gpt-4.1-mini",
            api_key=secret,
            base_url="https://api.openai.test/v1",
            http_client=client,
        )
        criteria, from_cache = await EligibilityExtractor(repository, provider).extract(study)

    assert from_cache is False
    assert len(requests) == 2
    assert "condition + equals" in requests[0]["messages"][0]["content"]
    repair_message = requests[1]["messages"][-1]["content"]
    assert "criteria.0.predicate" in repair_message
    assert "condition requires a fact operator" in repair_message
    assert secret not in json.dumps(requests)
    assert len(criteria) == 1
    assert criteria[0].predicate.attribute.value == "unsupported"
    assert criteria[0].predicate.operator.value == "unsupported"
    assert provider.last_usage is not None
    assert provider.last_usage.model_dump() == {
        "prompt_tokens": 200,
        "completion_tokens": 100,
        "total_tokens": 300,
    }


@pytest.mark.asyncio
async def test_multi_clause_semantic_failure_gets_one_safe_repair(study_factory, tmp_path):
    source = "Participants must be adults and have no prior surgery."
    study = study_factory(eligibility=source)
    invalid = valid_payload()
    invalid["criteria"][0]["original_text"] = source
    repaired = valid_payload()
    repaired["criteria"][0]["original_text"] = source
    repaired["criteria"][0]["predicate"] = {
        "attribute": "unsupported",
        "operator": "unsupported",
    }

    class Provider(FakeProvider):
        async def repair(self, study, invalid_payload, feedback):
            assert feedback[0]["path"] == "criteria.0.predicate"
            assert "multi-clause" in feedback[0]["message"]
            return repaired

    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    repository.upsert_studies([study])
    criteria, cached = await EligibilityExtractor(repository, Provider(invalid)).extract(study)

    assert cached is False
    assert criteria[0].predicate.operator.value == "unsupported"
