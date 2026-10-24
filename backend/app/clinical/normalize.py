"""ClinicalTrials.gov normalization and source-structured criterion generation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from .models import (
    CriterionAttribute,
    CriterionClassification,
    CriterionOperator,
    Predicate,
    SourceStudy,
    StructuredCriterion,
    Study,
    StudyContact,
    StudyLocation,
)


class StudyNormalizationError(ValueError):
    pass


def normalize_study(record: dict[str, Any], retrieved_at: datetime | None = None) -> Study:
    try:
        source = SourceStudy.model_validate(record)
    except ValidationError as exc:
        raise StudyNormalizationError(f"source schema validation failed: {exc}") from exc

    identification = source.protocol.identification
    if not identification.brief_title or not identification.brief_title.strip():
        raise StudyNormalizationError(f"{identification.nct_id}: BriefTitle is missing")
    if not source.protocol.status.overall_status:
        raise StudyNormalizationError(f"{identification.nct_id}: OverallStatus is missing")

    locations: list[StudyLocation] = []
    contacts: list[StudyContact] = []
    for location in source.protocol.contacts_locations.locations:
        locations.append(
            StudyLocation(
                facility=location.facility,
                city=location.city,
                state=location.state,
                postal_code=location.postal_code,
                country=location.country,
                latitude=location.geo_point.latitude if location.geo_point else None,
                longitude=location.geo_point.longitude if location.geo_point else None,
            )
        )
        contacts.extend(
            StudyContact(**contact.model_dump(), facility=location.facility) for contact in location.contacts
        )
    contacts.extend(
        StudyContact(**contact.model_dump(), facility=None)
        for contact in source.protocol.contacts_locations.central_contacts
    )
    unique_contacts: list[StudyContact] = []
    seen_contacts: set[tuple[str | None, ...]] = set()
    for contact in contacts:
        key = (contact.name, contact.role, contact.phone, contact.email, contact.facility)
        if key not in seen_contacts:
            seen_contacts.add(key)
            unique_contacts.append(contact)

    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
    source_hash = hashlib.sha256(canonical.encode()).hexdigest()
    eligibility = source.protocol.eligibility
    return Study(
        nct_id=identification.nct_id,
        title=identification.brief_title.strip(),
        overall_status=source.protocol.status.overall_status,
        conditions=[value.strip() for value in source.protocol.conditions.conditions if value.strip()],
        phases=[value.strip() for value in source.protocol.design.phases if value.strip()],
        eligibility_criteria=eligibility.eligibility_criteria,
        minimum_age=eligibility.minimum_age,
        maximum_age=eligibility.maximum_age,
        sex=eligibility.sex,
        locations=locations,
        contacts=unique_contacts,
        source_url=f"https://clinicaltrials.gov/study/{identification.nct_id}",
        retrieved_at=retrieved_at or datetime.now(UTC),
        source_hash=source_hash,
        raw_source=record,
    )


def source_missing_values(study: Study) -> dict[str, int]:
    return {
        "Condition": int(not study.conditions),
        "Phase": int(not study.phases),
        "EligibilityCriteria": int(not study.eligibility_criteria),
        "MinimumAge": int(not study.minimum_age),
        "MaximumAge": int(not study.maximum_age),
        "Sex": int(not study.sex),
        "Locations": int(not study.locations),
        "Contacts": int(not study.contacts),
    }


def source_structured_criteria(study: Study, created_at: datetime | None = None) -> list[StructuredCriterion]:
    """Create deterministic criteria only from official structured age/sex fields."""

    timestamp = created_at or datetime.now(UTC)
    criteria: list[StructuredCriterion] = []
    minimum = _age_to_years(study.minimum_age)
    maximum = _age_to_years(study.maximum_age)
    if minimum is not None and study.minimum_age:
        criteria.append(
            _criterion(
                study,
                suffix="source-min-age",
                text=f"Minimum Age: {study.minimum_age}",
                predicate=Predicate(
                    attribute=CriterionAttribute.AGE_YEARS,
                    operator=CriterionOperator.GREATER_THAN_OR_EQUAL,
                    value=minimum,
                    unit="years",
                ),
                created_at=timestamp,
            )
        )
    if maximum is not None and study.maximum_age:
        criteria.append(
            _criterion(
                study,
                suffix="source-max-age",
                text=f"Maximum Age: {study.maximum_age}",
                predicate=Predicate(
                    attribute=CriterionAttribute.AGE_YEARS,
                    operator=CriterionOperator.LESS_THAN_OR_EQUAL,
                    value=maximum,
                    unit="years",
                ),
                created_at=timestamp,
            )
        )
    if study.sex and study.sex.casefold() not in {"all", "unknown"}:
        criteria.append(
            _criterion(
                study,
                suffix="source-sex",
                text=f"Sex: {study.sex}",
                predicate=Predicate(
                    attribute=CriterionAttribute.SEX,
                    operator=CriterionOperator.EQUALS,
                    value=study.sex.casefold(),
                ),
                created_at=timestamp,
            )
        )
    return criteria


def _criterion(
    study: Study, *, suffix: str, text: str, predicate: Predicate, created_at: datetime
) -> StructuredCriterion:
    return StructuredCriterion(
        criterion_id=f"{study.nct_id}-{suffix}",
        nct_id=study.nct_id,
        classification=CriterionClassification.INCLUSION,
        original_text=text,
        predicate=predicate,
        source_url=study.source_url,
        extraction_uncertainty=None,
        extraction_method="source_structured",
        provider=None,
        model=None,
        source_hash=study.source_hash,
        created_at=created_at,
    )


def _age_to_years(value: str | None) -> float | None:
    if not value:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s+(Year|Years|Month|Months|Week|Weeks|Day|Days)\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).casefold()
    if unit.startswith("year"):
        return number
    if unit.startswith("month"):
        return number / 12
    if unit.startswith("week"):
        return number / 52.1429
    return number / 365.2425
