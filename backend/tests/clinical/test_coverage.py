from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from backend.app.clinical.database import ClinicalRepository
from backend.app.clinical.extraction import (
    EligibilityExtractor,
    ExtractionError,
    InvalidExtraction,
    ProviderUnavailable,
)
from backend.app.clinical.matching import MatchingService
from backend.app.clinical.models import ScreeningStatus, SyntheticPatient
from backend.app.clinical.normalize import source_structured_criteria


class CoverageProvider:
    name = "coverage-provider"
    model = "coverage-model"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def extract(self, study):
        self.calls += 1
        return self.payload


class ChangedSourceFailingProvider:
    name = "coverage-provider"
    model = "coverage-model"

    async def extract(self, study):
        raise ProviderUnavailable("configured provider unavailable")


def complete_payload(nct_id="NCT00000001"):
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


def partial_payload(nct_id="NCT00000001"):
    return {
        "nct_id": nct_id,
        "coverage": {
            "status": "partial",
            "protocol_item_count": 2,
            "accounted_item_count": 1,
            "uncovered_items": [
                {
                    "source_item_id": "item-002",
                    "original_text": "No prior surgery.",
                    "reason": "The temporal scope was not represented.",
                }
            ],
        },
        "criteria": complete_payload(nct_id)["criteria"],
    }


def approve_complete_coverage(repository, study, provider=None):
    selected_provider = provider or CoverageProvider(complete_payload(study.nct_id))
    cache_key = EligibilityExtractor(repository, selected_provider).cache_key(study)
    repository.approve_extraction_coverage(
        cache_key,
        verification_method="deterministic_test_fixture",
        verified_at=datetime(2026, 10, 24, 18, 0, tzinfo=UTC),
    )


def profile(age):
    return SyntheticPatient(profile_id="synthetic-coverage", synthetic=True, age_years=age)


@pytest.mark.asyncio
async def test_source_structured_age_sex_alone_remains_unresolved(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    repository.replace_criteria(
        study.nct_id, "source_structured", source_structured_criteria(study)
    )

    result = MatchingService(repository).match(profile(40)).results[0]

    assert result.screening_status == ScreeningStatus.UNRESOLVED
    assert result.extraction_coverage.status == "not_attempted"
    assert "full-protocol extraction coverage" in result.extraction_coverage.reason
    assert all(item.source_url == study.source_url for item in result.criteria)


@pytest.mark.asyncio
async def test_partial_protocol_coverage_stays_unresolved_with_source_gap(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory(
        eligibility="Participants must be 18 years or older.\nNo prior surgery."
    )
    repository.upsert_studies([study])
    await EligibilityExtractor(repository, CoverageProvider(partial_payload())).extract(study)

    result = MatchingService(repository).match(profile(40)).results[0]

    assert result.screening_status == ScreeningStatus.UNRESOLVED
    assert result.extraction_coverage.status == "partial"
    assert result.extraction_coverage.uncovered_protocol_requirement_count == 1
    assert any("No prior surgery." in item for item in result.unresolved_requirements)
    assert result.criteria[0].source_url == study.source_url


@pytest.mark.asyncio
async def test_explicit_complete_supported_coverage_can_be_potential_match(
    study_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    await EligibilityExtractor(repository, CoverageProvider(complete_payload())).extract(study)
    approve_complete_coverage(repository, study)

    result = MatchingService(repository).match(profile(40)).results[0]

    assert result.screening_status == ScreeningStatus.POTENTIAL_MATCH
    assert result.extraction_coverage.status == "complete"
    assert result.extraction_coverage.protocol_item_count == 1
    assert result.extraction_coverage.evaluable_criterion_count == 1
    assert result.unresolved_requirements == []


@pytest.mark.asyncio
async def test_complete_coverage_with_unknown_patient_fact_is_unresolved(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    await EligibilityExtractor(repository, CoverageProvider(complete_payload())).extract(study)
    approve_complete_coverage(repository, study)

    result = MatchingService(repository).match(profile(None)).results[0]

    assert result.screening_status == ScreeningStatus.UNRESOLVED
    assert result.extraction_coverage.status == "complete"
    assert result.criteria[0].status == "unknown"
    assert "age" in result.missing_questions[0].casefold()


@pytest.mark.asyncio
async def test_known_mismatch_dominates_incomplete_coverage(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory(
        eligibility="Participants must be 18 years or older.\nNo prior surgery."
    )
    repository.upsert_studies([study])
    await EligibilityExtractor(repository, CoverageProvider(partial_payload())).extract(study)

    result = MatchingService(repository).match(profile(17)).results[0]

    assert result.screening_status == ScreeningStatus.KNOWN_MISMATCH
    assert result.known_mismatches == ["Participants must be 18 years or older."]
    assert result.extraction_coverage.status == "partial"


@pytest.mark.asyncio
async def test_invalid_new_provider_output_cannot_replace_valid_current_generation(
    study_factory, tmp_path
):
    database_path = tmp_path / "clinical.sqlite3"
    repository = ClinicalRepository(database_path)
    study = study_factory()
    repository.upsert_studies([study])
    await EligibilityExtractor(repository, CoverageProvider(complete_payload())).extract(study)
    approve_complete_coverage(repository, study)
    invalid_provider = CoverageProvider(
        {
            **complete_payload(),
            "coverage": {
                "status": "complete",
                "protocol_item_count": 2,
                "accounted_item_count": 1,
                "uncovered_items": [],
            },
        }
    )
    invalid_provider.model = "different-model"

    with pytest.raises(InvalidExtraction):
        await EligibilityExtractor(repository, invalid_provider).extract(study)

    result = MatchingService(repository).match(profile(40)).results[0]
    assert result.screening_status == ScreeningStatus.POTENTIAL_MATCH
    assert result.extraction_coverage.status == "complete"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_changed_source_never_uses_old_criteria_and_cleans_up_after_success(
    study_factory, tmp_path
):
    database_path = tmp_path / "clinical.sqlite3"
    repository = ClinicalRepository(database_path)
    original = study_factory(title="Original source")
    repository.upsert_studies([original])
    await EligibilityExtractor(repository, CoverageProvider(complete_payload())).extract(original)
    approve_complete_coverage(repository, original)
    changed = study_factory(title="Changed source")
    repository.upsert_studies([changed])

    with pytest.raises(ProviderUnavailable):
        await EligibilityExtractor(repository, ChangedSourceFailingProvider()).extract(changed)
    failed_result = MatchingService(repository).match(profile(40)).results[0]
    assert failed_result.screening_status == ScreeningStatus.UNRESOLVED
    assert failed_result.extraction_coverage.status == "failed"
    assert failed_result.criteria == []

    await EligibilityExtractor(repository, CoverageProvider(complete_payload())).extract(changed)
    approve_complete_coverage(repository, changed)
    current_result = MatchingService(repository).match(profile(40)).results[0]
    assert current_result.screening_status == ScreeningStatus.POTENTIAL_MATCH
    with sqlite3.connect(database_path) as connection:
        hashes = connection.execute(
            "SELECT DISTINCT source_hash FROM extraction_cache"
        ).fetchall()
    assert hashes == [(changed.source_hash,)]


@pytest.mark.asyncio
async def test_malformed_cached_payload_is_removed_before_provider_fallback(
    study_factory, tmp_path
):
    database_path = tmp_path / "clinical.sqlite3"
    repository = ClinicalRepository(database_path)
    study = study_factory()
    repository.upsert_studies([study])
    provider = CoverageProvider(complete_payload())
    extractor = EligibilityExtractor(repository, provider)
    key = extractor.cache_key(study)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO extraction_cache (
                cache_key, nct_id, source_hash, provider, model, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                study.nct_id,
                study.source_hash,
                provider.name,
                provider.model,
                "{invalid-json",
                "2026-10-24T18:00:00+00:00",
            ),
        )
        connection.commit()

    criteria, from_cache = await extractor.extract(study)
    approve_complete_coverage(repository, study, provider)

    assert from_cache is False
    assert provider.calls == 1
    assert len(criteria) == 1
    assert MatchingService(repository).match(profile(40)).results[0].screening_status == "potential_match"


@pytest.mark.asyncio
async def test_partial_extraction_cannot_downgrade_complete_current_coverage(
    study_factory, tmp_path
):
    database_path = tmp_path / "clinical.sqlite3"
    repository = ClinicalRepository(database_path)
    study = study_factory()
    complete = complete_payload()
    complete["coverage"] = {
        "status": "complete",
        "protocol_item_count": 1,
        "accounted_item_count": 1,
        "uncovered_items": [],
    }
    repository.upsert_studies([study])
    await EligibilityExtractor(repository, CoverageProvider(complete)).extract(study)
    approve_complete_coverage(repository, study)
    partial_provider = CoverageProvider(
        {
            "nct_id": study.nct_id,
            "coverage": {
                "status": "partial",
                "protocol_item_count": 1,
                "accounted_item_count": 0,
                "uncovered_items": [
                    {
                        "source_item_id": "item-001",
                        "original_text": "Participants must be 18 years or older.",
                        "reason": "not processed",
                    }
                ],
            },
            "criteria": [],
        }
    )
    partial_provider.model = "new-partial-model"

    with pytest.raises(ExtractionError, match="refusing to replace complete"):
        await EligibilityExtractor(repository, partial_provider).extract(study)

    result = MatchingService(repository).match(profile(40)).results[0]
    assert result.extraction_coverage.status == "complete"
    assert result.screening_status == "potential_match"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_multi_clause_line_cannot_be_complete_with_single_clause_predicate(
    study_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    source_line = "Participants must be at least 18 years old and have no prior surgery."
    study = study_factory(eligibility=source_line)
    repository.upsert_studies([study])
    payload = complete_payload()
    payload["criteria"][0]["original_text"] = source_line

    with pytest.raises(InvalidExtraction, match="multi-clause"):
        await EligibilityExtractor(repository, CoverageProvider(payload)).extract(study)


@pytest.mark.asyncio
async def test_fully_supported_compound_counts_as_evaluable(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    source_line = "Adults from age 18 through age 64."
    study = study_factory(eligibility=source_line)
    repository.upsert_studies([study])
    payload = {
        "nct_id": study.nct_id,
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
                "original_text": source_line,
                "predicate": {
                    "attribute": "unsupported",
                    "operator": "all",
                    "children": [
                        {
                            "attribute": "age_years",
                            "operator": "greater_than_or_equal",
                            "value": 18,
                        },
                        {
                            "attribute": "age_years",
                            "operator": "less_than_or_equal",
                            "value": 64,
                        },
                    ],
                },
                "uncertainty": None,
            }
        ],
    }
    await EligibilityExtractor(repository, CoverageProvider(payload)).extract(study)
    approve_complete_coverage(repository, study)

    result = MatchingService(repository).match(profile(40)).results[0]

    assert result.screening_status == "potential_match"
    assert result.extraction_coverage.evaluable_criterion_count == 1
    assert result.extraction_coverage.unsupported_protocol_requirement_count == 0


@pytest.mark.asyncio
async def test_unsupported_protocol_requirement_is_distinct_from_unknown_patient_fact(
    study_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    source_line = "Specialist review of pathology is required."
    study = study_factory(eligibility=source_line)
    repository.upsert_studies([study])
    payload = {
        "nct_id": study.nct_id,
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
                "original_text": source_line,
                "predicate": {
                    "attribute": "unsupported",
                    "operator": "unsupported",
                },
                "uncertainty": "Requires specialist interpretation.",
            }
        ],
    }
    await EligibilityExtractor(repository, CoverageProvider(payload)).extract(study)
    approve_complete_coverage(repository, study)

    result = MatchingService(repository).match(profile(40)).results[0]

    assert result.screening_status == "unresolved"
    assert result.extraction_coverage.status == "complete"
    assert result.extraction_coverage.unsupported_protocol_requirement_count == 1
    assert result.extraction_coverage.uncovered_protocol_requirement_count == 0
    assert result.criteria[0].status == "unknown"
    assert "outside the supported deterministic vocabulary" in result.criteria[0].explanation


@pytest.mark.asyncio
async def test_provider_declared_complete_range_without_independent_review_stays_unresolved(
    study_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    source_line = "Adults from age 18 through age 64."
    study = study_factory(eligibility=source_line)
    repository.upsert_studies([study])
    payload = complete_payload()
    payload["criteria"][0]["original_text"] = source_line
    await EligibilityExtractor(repository, CoverageProvider(payload)).extract(study)

    result = MatchingService(repository).match(profile(70)).results[0]

    assert result.screening_status == "unresolved"
    assert result.extraction_coverage.status == "partial"
    assert result.extraction_coverage.independently_verified is False
    assert result.extraction_coverage.verification_method is None
    assert "no independent" in result.extraction_coverage.reason
