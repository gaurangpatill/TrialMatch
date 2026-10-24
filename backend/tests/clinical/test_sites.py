from __future__ import annotations

import json
from datetime import UTC, datetime

from backend.app.clinical.database import ClinicalRepository
from backend.app.clinical.normalize import normalize_study
from backend.app.clinical.sites import TrialSiteExport, build_site_export, write_site_export


def _study(source_record_factory, nct_id: str, locations: list[dict], conditions=None):
    raw = source_record_factory(nct_id, conditions=conditions or ["Cancer"])
    raw["protocolSection"]["contactsLocationsModule"]["locations"] = locations
    return normalize_study(raw, datetime(2026, 10, 24, 18, 0, tzinfo=UTC))


def test_export_filters_deduplicates_and_preserves_relationships(
    source_record_factory, tmp_path
):
    resolved = {
        "facility": "Mass General Hospital",
        "city": "Boston",
        "state": "Massachusetts",
        "zip": "02114",
        "country": "United States",
        "status": "RECRUITING",
        "geoPoint": {"lat": 42.3632, "lon": -71.0686},
    }
    unresolved = {
        "facility": "Community Clinic",
        "city": "Worcester",
        "state": "MA",
        "country": "United States",
        "status": "RECRUITING",
    }
    out_of_state = {**resolved, "facility": "New York Site", "state": "New York"}
    inactive = {**resolved, "facility": "Completed Site", "status": "COMPLETED"}
    missing_name = {**resolved, "facility": "  "}
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    repository.upsert_studies(
        [
            _study(
                source_record_factory,
                "NCT00000001",
                [resolved, dict(resolved), unresolved, out_of_state, inactive, missing_name],
            ),
            _study(source_record_factory, "NCT00000002", [resolved], conditions=["Diabetes"]),
        ]
    )

    export = build_site_export(
        repository,
        generated_at=datetime(2026, 10, 24, 18, 5, tzinfo=UTC),
        cohort_selection="Synthetic exporter fixture",
    )

    assert [(item.nct_id, item.facility_name) for item in export.records] == [
        ("NCT00000001", "Community Clinic"),
        ("NCT00000001", "Mass General Hospital"),
        ("NCT00000002", "Mass General Hospital"),
    ]
    assert export.metadata.source_location_count == 7
    assert export.metadata.explicit_massachusetts_location_count == 6
    assert export.metadata.excluded_non_recruiting_or_unknown_site_status_count == 1
    assert export.metadata.excluded_missing_facility_name_count == 1
    assert export.metadata.duplicate_record_count == 1
    assert export.metadata.exported_record_count == 3
    assert export.metadata.exported_study_count == 2
    assert export.metadata.unique_facility_location_count == 2
    assert export.metadata.resolved_coordinate_count == 2
    assert export.metadata.unresolved_coordinate_count == 1
    assert export.records[0].latitude is None
    assert export.records[0].coordinate_status == "unresolved"
    assert export.records[1].coordinate_status == "verified"
    assert export.records[1].coordinate_source


def test_invalid_source_coordinates_remain_unresolved(source_record_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    repository.upsert_studies(
        [
            _study(
                source_record_factory,
                "NCT00000001",
                [
                    {
                        "facility": "Invalid Coordinate Site",
                        "city": "Boston",
                        "state": "Massachusetts",
                        "country": "United States",
                        "status": "RECRUITING",
                        "geoPoint": {"lat": 999, "lon": -71},
                    }
                ],
            )
        ]
    )

    export = build_site_export(repository)

    assert export.metadata.invalid_source_coordinate_count == 1
    assert export.metadata.unresolved_coordinate_count == 1
    assert export.records[0].latitude is None
    assert export.records[0].longitude is None
    assert export.records[0].coordinate_source is None


def test_geography_mapping_has_exact_handoff_fields(source_record_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    repository.upsert_studies(
        [
            _study(
                source_record_factory,
                "NCT00000001",
                [
                    {
                        "facility": "Source Site",
                        "facilityId": "facility-1",
                        "city": "Boston",
                        "state": "Massachusetts",
                        "zip": "02115",
                        "country": "United States",
                        "status": "RECRUITING",
                        "geoPoint": {"lat": 42.3, "lon": -71.1},
                    }
                ],
            )
        ]
    )

    item = build_site_export(repository).geography_records[0].model_dump(mode="json")

    assert set(item) == {
        "nct_id",
        "conditions",
        "facility_source_id",
        "facility_name",
        "city",
        "state",
        "postal_code",
        "country",
        "latitude",
        "longitude",
        "coordinate_source",
        "coordinate_source_reference",
        "resolution_status",
        "overall_status",
        "source_url",
        "retrieved_at",
    }
    assert item["facility_source_id"] == "facility-1"
    assert item["resolution_status"] == "source_coordinates"


def test_export_serialization_is_valid_and_stably_ordered(source_record_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    locations = [
        {
            "facility": name,
            "city": "Boston",
            "state": "Massachusetts",
            "country": "United States",
            "status": "RECRUITING",
        }
        for name in ["Zulu Site", "Alpha Site"]
    ]
    repository.upsert_studies([_study(source_record_factory, "NCT00000001", locations)])
    generated_at = datetime(2026, 10, 24, 18, 5, tzinfo=UTC)
    first = build_site_export(repository, generated_at=generated_at)
    second = build_site_export(repository, generated_at=generated_at)
    output = tmp_path / "ma_trial_sites.json"

    write_site_export(first, output)
    loaded = TrialSiteExport.model_validate_json(output.read_text())

    assert first.model_dump_json() == second.model_dump_json()
    assert [item.facility_name for item in loaded.records] == ["Alpha Site", "Zulu Site"]
    raw = json.loads(output.read_text())
    assert len(raw["records"]) == raw["metadata"]["exported_record_count"]
    assert len(raw["geography_records"]) == len(raw["records"])
