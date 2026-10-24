from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.geography.models import (
    AcquisitionReport,
    DerivedMetricDefinition,
    NormalizedBlockGroup,
    RawEJAttributes,
    TrialSite,
)
from backend.app.geography.repository import SQLiteGeographyRepository


def test_raw_schema_requires_all_declared_fields_and_valid_units() -> None:
    with pytest.raises(ValidationError):
        RawEJAttributes.model_validate({"source_id": "1", "MUNICIPALITY": "Boston"})
    with pytest.raises(ValidationError, match="percentage points"):
        RawEJAttributes(
            source_id="1", MUNICIPALITY="Boston", TOTAL_POP=10, PCT_MINORITY=101,
            LIMENGHHPCT=1, BG_MHHI=50_000, EJ="Yes", EJ_CRIT_DESC=None,
        )


def test_normalized_model_is_explicitly_aggregate_and_geometryless() -> None:
    record = NormalizedBlockGroup(
        source_id="7", municipality="Boston", total_population=None,
        percent_minority=None, limited_english_household_percent=12.5,
        block_group_median_household_income_usd=None, ej_flag="Yes",
        ej_criteria_description=None,
    )
    assert record.percent_unit == "percentage_points_0_to_100"
    assert record.source_scope == "aggregate_community_block_group"
    assert record.geometry is None
    assert "patient" not in NormalizedBlockGroup.model_fields
    with pytest.raises(ValidationError):
        NormalizedBlockGroup(**record.model_dump(), patient_count=3)


def test_site_and_derived_metric_boundaries_validate() -> None:
    site = TrialSite(nct_id="NCT00000001", facility_name="Synthetic Site")
    assert site.latitude is None
    definition = DerivedMetricDefinition(
        name="future_access", version="1", direction="higher_is_more_access",
        scale="0..100", components=("distance",), assumptions=("modeled",),
        missing_data_behavior="null",
    )
    assert definition.missing_data_behavior == "null"


def test_sqlite_schema_preserves_nulls_units_and_run_evidence(tmp_path) -> None:
    repository = SQLiteGeographyRepository(tmp_path / "geo.sqlite")
    repository.initialize()
    record = NormalizedBlockGroup(
        source_id="7", municipality="Boston", total_population=None,
        percent_minority=None, limited_english_household_percent=12.5,
        block_group_median_household_income_usd=None, ej_flag="Yes",
        ej_criteria_description=None,
    )
    repository.replace_block_groups((record,))
    now = datetime.now(timezone.utc)
    report = AcquisitionReport(
        source_url="https://example.test/0", object_id_field="OBJECTID",
        out_fields=("OBJECTID",), page_size=100, started_at_utc=now,
        finished_at_utc=now, expected_source_count=1, fetched_record_count=1,
        unique_accepted_count=1, duplicate_count=0, invalid_quarantined_count=0,
        page_count=1, retry_count=0, complete=True, termination_reason="complete",
        query_parameters={"where": "EJ='Yes'"},
    )
    run_id = repository.save_acquisition_report(report)
    with sqlite3.connect(tmp_path / "geo.sqlite") as connection:
        row = connection.execute(
            "SELECT total_population, percent_minority, percent_unit, source_scope FROM geography_block_groups"
        ).fetchone()
        stored_complete = connection.execute(
            "SELECT complete FROM geography_acquisition_runs WHERE id = ?", (run_id,)
        ).fetchone()[0]
    assert row == (None, None, "percentage_points_0_to_100", "aggregate_community_block_group")
    assert stored_complete == 1


def test_raw_snapshot_cache_is_atomic_canonical_and_checksummed(tmp_path) -> None:
    import hashlib

    from backend.app.geography.models import IngestionResult

    repository = SQLiteGeographyRepository(tmp_path / "geo.sqlite")
    now = datetime.now(timezone.utc)
    report = AcquisitionReport(
        source_url="https://example.test/0", object_id_field="OBJECTID",
        out_fields=("OBJECTID",), page_size=100, started_at_utc=now,
        finished_at_utc=now, expected_source_count=1, fetched_record_count=1,
        unique_accepted_count=1, duplicate_count=0, invalid_quarantined_count=0,
        page_count=1, retry_count=0, complete=True, termination_reason="complete",
        query_parameters={"where": "EJ='Yes'"},
    )
    raw = RawEJAttributes(
        source_id="1", MUNICIPALITY="Boston", TOTAL_POP=None, PCT_MINORITY=None,
        LIMENGHHPCT=10, BG_MHHI=None, EJ="Yes", EJ_CRIT_DESC=None,
    )
    result = IngestionResult(records=(raw,), report=report)
    destination = tmp_path / "cache" / "ej.json"
    checksum = repository.cache_raw_records(result, destination)
    assert checksum == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert result.report.raw_snapshot_sha256 == checksum
    assert result.report.raw_snapshot_record_count == 1
    assert '"TOTAL_POP":null' in destination.read_text()
    assert not list(destination.parent.glob("*.tmp"))
