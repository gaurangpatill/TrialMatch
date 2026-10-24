"""Explicit synthetic source-shaped fixtures for Clinical Intelligence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.clinical.models import (
    CriterionAttribute,
    CriterionClassification,
    CriterionOperator,
    Predicate,
    StructuredCriterion,
    Study,
)
from backend.app.clinical.normalize import normalize_study


@pytest.fixture
def source_record_factory():
    def make(
        nct_id: str = "NCT00000001",
        *,
        title: str = "Synthetic Test Study",
        status: str = "RECRUITING",
        conditions: list[str] | None = None,
        phases: list[str] | None = None,
        eligibility: str | None = "Participants must be 18 years or older.",
        minimum_age: str | None = "18 Years",
        maximum_age: str | None = "65 Years",
        sex: str | None = "ALL",
    ) -> dict[str, Any]:
        protocol: dict[str, Any] = {
            "identificationModule": {"nctId": nct_id, "briefTitle": title},
            "statusModule": {"overallStatus": status},
            "conditionsModule": {"conditions": conditions or ["Synthetic condition"]},
            "designModule": {"phases": phases or ["PHASE2"]},
            "contactsLocationsModule": {
                "centralContacts": [
                    {"name": "Synthetic Contact", "role": "CONTACT", "email": "test@example.invalid"}
                ],
                "locations": [
                    {
                        "facility": "Synthetic Facility",
                        "status": "RECRUITING",
                        "city": "Boston",
                        "state": "Massachusetts",
                        "zip": "02108",
                        "country": "United States",
                        "geoPoint": {"lat": 42.36, "lon": -71.06},
                    }
                ],
            },
        }
        if any(value is not None for value in (eligibility, minimum_age, maximum_age, sex)):
            protocol["eligibilityModule"] = {
                key: value
                for key, value in {
                    "eligibilityCriteria": eligibility,
                    "minimumAge": minimum_age,
                    "maximumAge": maximum_age,
                    "sex": sex,
                }.items()
                if value is not None
            }
        return {"protocolSection": protocol}

    return make


@pytest.fixture
def study_factory(source_record_factory):
    def make(nct_id: str = "NCT00000001", **kwargs: Any) -> Study:
        return normalize_study(
            source_record_factory(nct_id, **kwargs),
            datetime(2026, 10, 24, 17, 0, tzinfo=UTC),
        )

    return make


@pytest.fixture
def criterion_factory(study_factory):
    def make(
        *,
        nct_id: str = "NCT00000001",
        classification: CriterionClassification = CriterionClassification.INCLUSION,
        attribute: CriterionAttribute = CriterionAttribute.AGE_YEARS,
        operator: CriterionOperator = CriterionOperator.GREATER_THAN_OR_EQUAL,
        target: str | None = None,
        value: str | int | float | bool | None = 18,
        lower: float | None = None,
        upper: float | None = None,
        unit: str | None = None,
        temporal_window_days: int | None = None,
        children: list[Predicate] | None = None,
        text: str = "Participants must be 18 years or older.",
        criterion_id: str = "fixture-criterion",
    ) -> StructuredCriterion:
        study = study_factory(nct_id)
        return StructuredCriterion(
            criterion_id=criterion_id,
            nct_id=nct_id,
            classification=classification,
            original_text=text,
            predicate=Predicate(
                attribute=attribute,
                operator=operator,
                target=target,
                value=value,
                lower=lower,
                upper=upper,
                unit=unit,
                temporal_window_days=temporal_window_days,
                children=children or [],
            ),
            source_url=study.source_url,
            extraction_method="test_fixture",
            source_hash=study.source_hash,
            created_at=datetime(2026, 10, 24, 17, 0, tzinfo=UTC),
        )

    return make
