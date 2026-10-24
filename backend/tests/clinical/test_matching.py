from __future__ import annotations

from datetime import UTC, datetime

from backend.app.clinical.database import ClinicalRepository
from backend.app.clinical.matching import MatchingService, find_contradictions
from backend.app.clinical.models import (
    CriterionClassification,
    ScreeningStatus,
    SyntheticPatient,
)


def test_matching_returns_mismatch_unknowns_and_evidence(
    study_factory, criterion_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    age = criterion_factory(value=18, criterion_id="age")
    unresolved = criterion_factory(
        criterion_id="age-unknown",
        value=70,
        text="Participants must be at least 70 years old.",
    )
    repository.replace_criteria(study.nct_id, "test_fixture", [age, unresolved])
    service = MatchingService(
        repository, clock=lambda: datetime(2026, 10, 24, 18, 0, tzinfo=UTC)
    )
    profile = SyntheticPatient(profile_id="synthetic-1", synthetic=True, age_years=40)

    response = service.match(profile, trial_ids=[study.nct_id])

    result = response.results[0]
    assert result.screening_status == ScreeningStatus.KNOWN_MISMATCH
    assert result.known_mismatches == ["Participants must be at least 70 years old."]
    assert all(item.source_url == study.source_url for item in result.criteria)
    assert response.disclaimer.startswith("Preliminary screening only")


def test_study_without_cached_criteria_is_unresolved(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    profile = SyntheticPatient(profile_id="synthetic-1", synthetic=True)

    result = MatchingService(repository).match(profile).results[0]

    assert result.screening_status == ScreeningStatus.UNRESOLVED
    assert "No current validated structured" in result.unresolved_requirements[0]


def test_contradictory_classifications_are_surfaced(criterion_factory):
    inclusion = criterion_factory(
        classification=CriterionClassification.INCLUSION,
        criterion_id="include",
    )
    exclusion = criterion_factory(
        classification=CriterionClassification.EXCLUSION,
        criterion_id="exclude",
    )
    warnings = find_contradictions([inclusion, exclusion])
    assert len(warnings) == 1
    assert "contradictory" in warnings[0].casefold()
