"""Pure validation, normalization, and EJ-subset aggregation functions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from .models import (
    MunicipalityEJSubsetAggregate,
    NormalizationResult,
    NormalizedBlockGroup,
    QuarantinedRecord,
    RawEJAttributes,
)

REQUIRED_ATTRIBUTES = (
    "MUNICIPALITY",
    "TOTAL_POP",
    "PCT_MINORITY",
    "LIMENGHHPCT",
    "BG_MHHI",
    "EJ",
    "EJ_CRIT_DESC",
)


def validate_raw_attributes(attributes: dict[str, Any], object_id_field: str) -> RawEJAttributes:
    missing = [name for name in (*REQUIRED_ATTRIBUTES, object_id_field) if name not in attributes]
    if missing:
        raise ValueError(f"missing required source field(s): {', '.join(missing)}")
    payload = {name: attributes[name] for name in REQUIRED_ATTRIBUTES}
    payload["source_id"] = attributes[object_id_field]
    return RawEJAttributes.model_validate(payload)


def normalize_record(raw: RawEJAttributes) -> NormalizedBlockGroup:
    if raw.MUNICIPALITY is None:
        raise ValueError("MUNICIPALITY is null")
    if raw.EJ != "Yes":
        raise ValueError("EJ must equal 'Yes' for the configured source subset")
    return NormalizedBlockGroup(
        source_id=raw.source_id,
        municipality=raw.MUNICIPALITY,
        total_population=raw.TOTAL_POP,
        percent_minority=raw.PCT_MINORITY,
        limited_english_household_percent=raw.LIMENGHHPCT,
        block_group_median_household_income_usd=raw.BG_MHHI,
        ej_flag=raw.EJ,
        ej_criteria_description=raw.EJ_CRIT_DESC,
    )


def normalize_records(records: Iterable[RawEJAttributes]) -> NormalizationResult:
    normalized: list[NormalizedBlockGroup] = []
    quarantined: list[QuarantinedRecord] = []
    seen: set[str] = set()
    for index, raw in enumerate(records):
        if raw.source_id in seen:
            quarantined.append(
                QuarantinedRecord(
                    page_offset=0,
                    record_index=index,
                    source_id=raw.source_id,
                    reason="duplicate source ID excluded from normalization",
                )
            )
            continue
        seen.add(raw.source_id)
        try:
            normalized.append(normalize_record(raw))
        except (ValueError, ValidationError) as exc:
            quarantined.append(
                QuarantinedRecord(
                    page_offset=0,
                    record_index=index,
                    source_id=raw.source_id,
                    reason=str(exc),
                )
            )
    return NormalizationResult(records=tuple(normalized), quarantined=tuple(quarantined))


def _weighted(
    records: list[NormalizedBlockGroup], attribute: str
) -> tuple[float | None, int, int]:
    numerator = 0.0
    denominator = 0
    missing_count = 0
    for record in records:
        population = record.total_population
        value = getattr(record, attribute)
        if population is None or value is None:
            missing_count += 1
            continue
        denominator += population
        numerator += population * value
    return (numerator / denominator if denominator > 0 else None, denominator, missing_count)


def aggregate_municipalities(
    records: Iterable[NormalizedBlockGroup],
) -> tuple[MunicipalityEJSubsetAggregate, ...]:
    """Aggregate only EJ-flagged block groups, never whole-municipality statistics."""

    grouped: dict[str, list[NormalizedBlockGroup]] = defaultdict(list)
    globally_seen: set[str] = set()
    for record in records:
        if record.source_id in globally_seen:
            continue
        globally_seen.add(record.source_id)
        grouped[record.municipality].append(record)

    aggregates: list[MunicipalityEJSubsetAggregate] = []
    for municipality in sorted(grouped, key=lambda value: (value.casefold(), value)):
        group = grouped[municipality]
        populations = [r.total_population for r in group if r.total_population is not None]
        minority, minority_denominator, minority_missing = _weighted(group, "percent_minority")
        english, english_denominator, english_missing = _weighted(
            group, "limited_english_household_percent"
        )
        income, income_denominator, income_missing = _weighted(
            group, "block_group_median_household_income_usd"
        )
        aggregates.append(
            MunicipalityEJSubsetAggregate(
                municipality=municipality,
                block_group_count=len(group),
                source_ids=tuple(sorted(record.source_id for record in group)),
                total_population_ej_subset=sum(populations) if populations else None,
                total_population_missing_count=len(group) - len(populations),
                percent_minority_population_weighted_ej_subset=minority,
                percent_minority_represented_population=minority_denominator,
                percent_minority_missing_count=minority_missing,
                limited_english_population_weighted_ej_subset=english,
                limited_english_represented_population=english_denominator,
                limited_english_missing_count=english_missing,
                block_group_median_household_income_population_weighted_mean_usd_ej_subset=income,
                income_represented_population=income_denominator,
                income_missing_count=income_missing,
            )
        )
    return tuple(aggregates)
