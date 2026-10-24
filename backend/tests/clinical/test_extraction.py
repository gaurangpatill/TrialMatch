from __future__ import annotations

import pytest

from backend.app.clinical.database import ClinicalRepository
from backend.app.clinical.extraction import (
    EligibilityExtractor,
    InvalidExtraction,
    ProviderUnavailable,
)


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
