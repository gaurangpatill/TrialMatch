from __future__ import annotations

import pytest

from backend.app.geography.models import NormalizedBlockGroup, RawEJAttributes
from backend.app.geography.transform import aggregate_municipalities, normalize_record, normalize_records


def raw(source_id: str = "1", **changes: object) -> RawEJAttributes:
    values = {
        "source_id": source_id,
        "MUNICIPALITY": "Boston",
        "TOTAL_POP": 100,
        "PCT_MINORITY": 20.0,
        "LIMENGHHPCT": 10.0,
        "BG_MHHI": 50_000.0,
        "EJ": "Yes",
        "EJ_CRIT_DESC": None,
    }
    values.update(changes)
    return RawEJAttributes.model_validate(values)


def normalized(source_id: str, municipality: str, population: int | None, minority: float | None,
               english: float | None, income: float | None) -> NormalizedBlockGroup:
    return NormalizedBlockGroup(
        source_id=source_id, municipality=municipality, total_population=population,
        percent_minority=minority, limited_english_household_percent=english,
        block_group_median_household_income_usd=income, ej_flag="Yes",
        ej_criteria_description=None,
    )


def test_normalization_preserves_percentage_points_and_nulls() -> None:
    result = normalize_record(raw(TOTAL_POP=None, PCT_MINORITY=None, BG_MHHI=None))
    assert result.total_population is None
    assert result.percent_minority is None
    assert result.block_group_median_household_income_usd is None
    assert result.percent_unit == "percentage_points_0_to_100"


def test_normalization_quarantines_wrong_subset_and_duplicate() -> None:
    result = normalize_records((raw("1"), raw("1"), raw("2", EJ="No")))
    assert [record.source_id for record in result.records] == ["1"]
    assert len(result.quarantined) == 2
    assert "duplicate" in result.quarantined[0].reason
    assert "EJ must equal" in result.quarantined[1].reason


def test_municipality_aggregation_is_weighted_labeled_and_deterministic() -> None:
    records = (
        normalized("2", "Boston", 300, 60, None, 70_000),
        normalized("1", "Boston", 100, 20, 10, 50_000),
        normalized("1", "Boston", 100, 20, 10, 50_000),  # excluded duplicate
        normalized("3", "Boston", None, 90, 30, 90_000),
        normalized("4", "Adams", 0, 50, 50, 40_000),
    )
    adams, boston = aggregate_municipalities(records)
    assert (adams.municipality, boston.municipality) == ("Adams", "Boston")
    assert "not full municipality" in boston.source_scope
    assert boston.block_group_count == 3
    assert boston.source_ids == ("1", "2", "3")
    assert boston.total_population_ej_subset == 400
    assert boston.total_population_missing_count == 1
    assert boston.percent_minority_population_weighted_ej_subset == pytest.approx(50)
    assert boston.percent_minority_represented_population == 400
    assert boston.percent_minority_missing_count == 1
    assert boston.limited_english_population_weighted_ej_subset == pytest.approx(10)
    assert boston.limited_english_represented_population == 100
    assert boston.limited_english_missing_count == 2
    assert boston.block_group_median_household_income_population_weighted_mean_usd_ej_subset == pytest.approx(65_000)
    assert boston.income_represented_population == 400
    assert boston.income_missing_count == 1
    assert "not a municipality median" in boston.income_statistic_note
    assert adams.percent_minority_population_weighted_ej_subset is None
    assert adams.percent_minority_represented_population == 0


def test_all_missing_population_stays_null_not_zero() -> None:
    aggregate = aggregate_municipalities((normalized("1", "Boston", None, 25, 10, 60_000),))[0]
    assert aggregate.total_population_ej_subset is None
    assert aggregate.percent_minority_population_weighted_ej_subset is None
    assert aggregate.income_represented_population == 0
