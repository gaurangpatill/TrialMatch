from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.geography.aggregate_snapshot import (
    load_aggregate_snapshot,
    save_aggregate_snapshot,
)
from backend.app.geography.router import (
    GeographyRuntime,
    geography_router,
    get_geography_runtime,
)
from backend.app.geography.sites import adapt_trial_sites, load_trial_site_export
from backend.app.optimizer import OptimizationResult, optimize


def client_for(runtime: GeographyRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(geography_router)
    app.dependency_overrides[get_geography_runtime] = lambda: runtime
    return TestClient(app)


@pytest.fixture
def unavailable_runtime(tmp_path: Path) -> GeographyRuntime:
    return GeographyRuntime(site_export_path=tmp_path / "absent-sites.json")


@pytest.fixture
def client(unavailable_runtime: GeographyRuntime) -> TestClient:
    return client_for(unavailable_runtime)


def test_actual_persisted_geo_returns_all_real_municipality_fields(client: TestClient) -> None:
    response = client.get("/api/geo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 187
    assert payload["summary"]["observed_feature_count"] == 187
    assert payload["summary"]["resolved_feature_count"] == 187
    assert payload["summary"]["unresolved_feature_count"] == 0
    assert payload["summary"]["source_filter"] == "EJ='Yes'"
    assert payload["summary"]["output_crs"] == "EPSG:4326"
    assert "MassGIS" in payload["summary"]["source_name"]
    assert payload["features"] == sorted(
        payload["features"], key=lambda row: (row["id"].casefold(), row["id"])
    )

    boston = next(row for row in payload["features"] if row["id"] == "Boston")
    assert boston["geometry"]["type"] == "Point"
    assert boston["geometry"]["coordinates"] == pytest.approx(
        [-71.09124969447807, 42.321809755146745]
    )
    properties = boston["properties"]
    assert properties["ej_subset_population"] == 571192
    assert properties["ej_block_group_count"] == 462
    assert properties["population_weighted_percent_minority_ej_subset"] is not None
    assert properties["population_weighted_limited_english_household_percent_ej_subset"] is not None
    assert properties["population_weighted_mean_block_group_median_household_income_usd_ej_subset"] is not None
    assert "not a municipality median" in properties["income_statistic_label"]
    assert "not full municipality" in properties["source_scope"]


def test_unavailable_export_is_null_not_zero_and_filter_is_deterministic(client: TestClient) -> None:
    response = client.get("/api/geo", params={"municipality": "bOsToN"})
    assert response.status_code == 200
    payload = response.json()
    assert [row["id"] for row in payload["features"]] == ["Boston"]
    assert payload["recruiting_site_features"] == []
    assert payload["available_conditions"] is None
    summary = payload["summary"]
    assert summary["clinical_site_data_available"] is False
    for field in (
        "clinical_site_accepted_count",
        "clinical_site_resolved_count",
        "clinical_site_unresolved_count",
        "clinical_site_deduplicated_count",
        "clinical_site_quarantined_count",
        "clinical_site_source_record_count",
        "clinical_site_schema_accepted_count",
        "clinical_site_massachusetts_recruiting_retained_count",
        "clinical_site_retained_count",
        "clinical_site_distinct_nct_count",
        "clinical_site_duplicate_removed_count",
        "clinical_site_unique_facility_location_count",
        "clinical_site_export_scope",
        "clinical_site_export_limitations",
        "clinical_site_coordinate_precision_limitation",
    ):
        assert summary[field] is None
    properties = payload["features"][0]["properties"]
    assert properties["nearest_resolved_recruiting_site_distance_km"] is None
    assert properties["distinct_nearby_recruiting_nct_count"] is None
    assert properties["access_radius_km"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"access_radius_km": -1},
        {"access_radius_km": 201},
        {"access_radius_km": "nan"},
        {"condition": ""},
    ],
)
def test_geo_query_validation(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/api/geo", params=params).status_code == 422


def test_condition_access_requires_export(client: TestClient) -> None:
    response = client.get("/api/geo", params={"condition": "Cancer"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CLINICAL_SITE_EXPORT_UNAVAILABLE"


def test_site_export_arrays_envelopes_aliases_statuses_and_bad_coordinates(tmp_path: Path) -> None:
    records = [
        {
            "nct_id": "NCT001",
            "conditions": ["Cancer"],
            "facility_name": "Source Coordinates",
            "city": "Boston",
            "state": "MA",
            "country": "US",
            "lat": 42.36,
            "lon": -71.06,
            "coordinate_status": "provided",
            "resolution_status": None,
            "recruiting_status": "Recruiting",
            "overall_status": None,
            "source_url": "https://example.test/NCT001",
            "retrieved_at": "2025-01-01T00:00:00Z",
        },
        {
            "nct_id": "NCT002",
            "conditions": ["Cancer"],
            "facility_name": "Unresolved",
            "city": "Boston",
            "state": "Massachusetts",
            "country": "US",
            "coordinate_status": "unknown",
            "recruiting_status": "RECRUITING",
        },
        {
            "nct_id": "NCT003",
            "conditions": ["Cancer"],
            "facility_name": "Bad Pair",
            "city": "Boston",
            "state": "MA",
            "country": "US",
            "latitude": 42.0,
            "recruiting_status": "Recruiting",
        },
        {
            "nct_id": "NCT004",
            "conditions": ["Cancer"],
            "facility_name": "Bad Range",
            "city": "Boston",
            "state": "MA",
            "country": "US",
            "latitude": 142.0,
            "longitude": -71.0,
            "recruiting_status": "Recruiting",
        },
    ]
    for key in (None, "records", "items", "sites"):
        path = tmp_path / f"sites-{key or 'array'}.json"
        payload: Any = records if key is None else {key: records}
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_trial_site_export(path)
        assert loaded.report.available is True
        assert loaded.report.input_count == 4
        assert loaded.report.accepted_count == 2
        assert loaded.report.quarantined_count == 2
        assert loaded.sites[0].resolution_status == "source_coordinates"
        assert loaded.sites[0].overall_status == "RECRUITING"
        assert loaded.sites[1].resolution_status == "unresolved"
        assert any("present together" in reason for reason in loaded.report.quarantine_reasons)
        assert any("outside valid" in reason for reason in loaded.report.quarantine_reasons)


def test_available_export_computes_access_and_reports_quarantine(tmp_path: Path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(
        json.dumps(
            {
                "sites": [
                    {
                        "nct_id": "NCT001",
                        "conditions": ["Cancer"],
                        "facility_name": "Boston Site",
                        "city": "Boston",
                        "state": "MA",
                        "country": "US",
                        "latitude": 42.321809755146745,
                        "longitude": -71.09124969447807,
                        "coordinate_status": "source_coordinates",
                        "recruiting_status": "recruiting",
                        "source_url": "https://example.test/NCT001",
                    },
                    {
                        "nct_id": "NCTBAD",
                        "conditions": ["Cancer"],
                        "facility_name": "Bad",
                        "city": "Boston",
                        "state": "MA",
                        "country": "US",
                        "latitude": 500,
                        "longitude": 0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    response = client_for(GeographyRuntime(site_export_path=path)).get(
        "/api/geo", params={"municipality": "Boston", "condition": "cancer", "access_radius_km": 5}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["available_conditions"] == ["Cancer"]
    assert len(payload["recruiting_site_features"]) == 1
    site_feature = payload["recruiting_site_features"][0]
    assert site_feature["type"] == "Feature"
    assert site_feature["geometry"]["coordinates"] == pytest.approx(
        [-71.09124969447807, 42.321809755146745]
    )
    assert site_feature["properties"]["nct_id"] == "NCT001"
    assert site_feature["properties"]["facility"] == "Boston Site"
    assert site_feature["properties"]["recruiting_status"] == "RECRUITING"
    assert "not independently verified" in site_feature["properties"]["coordinate_approximation_warning"]
    summary = payload["summary"]
    assert summary["clinical_site_data_available"] is True
    assert summary["clinical_site_source_record_count"] == 2
    assert summary["clinical_site_schema_accepted_count"] == 1
    assert summary["clinical_site_massachusetts_recruiting_retained_count"] == 1
    assert summary["clinical_site_retained_count"] == 1
    assert summary["clinical_site_distinct_nct_count"] == 1
    assert summary["clinical_site_duplicate_removed_count"] == 0
    assert summary["clinical_site_unique_facility_location_count"] == 1
    assert "scope metadata was not supplied" in summary["clinical_site_export_scope"]
    assert "not independently verified" in summary["clinical_site_coordinate_precision_limitation"]
    assert summary["clinical_site_accepted_count"] == 1
    assert payload["summary"]["clinical_site_resolved_count"] == 1
    assert payload["summary"]["clinical_site_unresolved_count"] == 0
    assert payload["summary"]["clinical_site_deduplicated_count"] == 1
    assert payload["summary"]["clinical_site_quarantined_count"] == 1
    properties = payload["features"][0]["properties"]
    assert properties["nearest_resolved_recruiting_site_distance_km"] == pytest.approx(0)
    assert properties["distinct_nearby_recruiting_nct_count"] == 1
    assert properties["access_radius_km"] == 5


def test_actual_post_runs_scipy_returns_coordinates_baselines_and_provenance(client: TestClient) -> None:
    response = client.post(
        "/api/optimize",
        json={"max_events": 3, "coverage_radius_km": 25, "equity_weight": 0.6},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "optimal"
    assert payload["solver"]["native_status"] == 0
    assert payload["solver"]["name"].startswith("scipy.optimize.milp")
    assert payload["solver"]["mip_gap"] == pytest.approx(0)
    assert payload["total_events"] == 3
    assert payload["total_cost"] == 3
    assert payload["cost_unit"] == "abstract_equal_event_units"
    assert len(payload["selected_locations"]) == 3
    assert all(-90 <= row["latitude"] <= 90 for row in payload["selected_locations"])
    assert all(-180 <= row["longitude"] <= 180 for row in payload["selected_locations"])
    explanations = {
        row["municipality_id"]: row["explanation"]
        for row in payload["selected_locations"]
    }
    assert set(explanations) == {"Hudson", "Reading", "Sharon"}
    assert set().union(
        *(set(explanation["raw_catchment_community_ids"]) for explanation in explanations.values())
    ) == set(payload["covered_municipality_ids"])
    uniquely_covered_sets = [
        set(explanation["uniquely_covered_community_ids"])
        for explanation in explanations.values()
    ]
    assert all(
        left.isdisjoint(right)
        for index, left in enumerate(uniquely_covered_sets)
        for right in uniquely_covered_sets[index + 1 :]
    )
    assert explanations["Hudson"]["raw_catchment_community_count"] == 21
    assert explanations["Hudson"]["uniquely_covered_community_count"] == 17
    assert explanations["Hudson"]["leave_one_out_objective_loss"] == pytest.approx(
        254466.43992313067
    )
    assert explanations["Reading"]["raw_catchment_ej_subset_population_proxy"] == 1734485
    assert explanations["Reading"]["uniquely_covered_ej_subset_population_proxy"] == 1718203
    assert explanations["Reading"]["leave_one_out_objective_loss"] == pytest.approx(
        1111982.0234593647
    )
    assert explanations["Sharon"]["raw_catchment_objective"] == pytest.approx(
        269252.9876298667
    )
    assert explanations["Sharon"]["uniquely_covered_objective"] == pytest.approx(
        264010.0919229359
    )
    assert all(
        "fixed-plan removal loss" in explanation["leave_one_out_interpretation"]
        and "not causal impact" in explanation["leave_one_out_interpretation"]
        and "reoptimized marginal value" in explanation["leave_one_out_interpretation"]
        for explanation in explanations.values()
    )
    assert payload["covered_municipality_count"] == len(payload["covered_municipality_ids"])
    assert {row["strategy"] for row in payload["baselines"]} == {
        "population_first_greedy",
        "equity_first_greedy",
    }
    assert payload["constraint_satisfaction"]["all_satisfied"] is True
    assert payload["scenario_construction"]["included_municipality_count"] == 187
    assert payload["scenario_construction"]["excluded_municipality_count"] == 0
    assert payload["provenance"]["aggregate_source_record_count"] == 2604
    assert payload["provenance"]["municipality_aggregate_count"] == 187
    assert payload["provenance"]["runtime_massgis_fetch"] is False
    assert any("not enrollment" in value for value in payload["limitations"])


def test_zero_events_returns_valid_optimal_empty_plan(client: TestClient) -> None:
    response = client.post(
        "/api/optimize",
        json={"max_events": 0, "coverage_radius_km": 25, "equity_weight": 0.6},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "optimal"
    assert payload["selected_locations"] == []
    assert payload["covered_municipality_ids"] == []
    assert payload["total_events"] == 0
    assert payload["total_cost"] == 0
    assert payload["modeled_outreach_coverage_objective"] == 0
    assert payload["constraint_satisfaction"]["all_satisfied"] is True


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"max_events": -1, "coverage_radius_km": 25, "equity_weight": 0.5},
        {"max_events": 21, "coverage_radius_km": 25, "equity_weight": 0.5},
        {"max_events": 1, "coverage_radius_km": -1, "equity_weight": 0.5},
        {"max_events": 1, "coverage_radius_km": 201, "equity_weight": 0.5},
        {"max_events": 1, "coverage_radius_km": 25, "equity_weight": 1.1},
        {"max_events": 1, "coverage_radius_km": 25, "equity_weight": 0.5, "extra": True},
        {"max_events": 1, "coverage_radius_km": 25, "equity_weight": 0.5, "condition": "  "},
    ],
)
def test_optimize_request_validation(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/optimize", json=body).status_code == 422


def test_each_changed_request_invokes_solver_and_recomputes(unavailable_runtime: GeographyRuntime) -> None:
    calls: list[tuple[int, float, float]] = []

    def spy(scenario: Any) -> OptimizationResult:
        calls.append(
            (scenario.max_events, scenario.coverage_radius_km, scenario.equity_weight_lambda)
        )
        return optimize(scenario)

    runtime = GeographyRuntime(
        site_export_path=unavailable_runtime.site_export_path,
        optimizer=spy,
    )
    client = client_for(runtime)
    bodies = [
        {"max_events": 1, "coverage_radius_km": 0, "equity_weight": 0},
        {"max_events": 2, "coverage_radius_km": 25, "equity_weight": 0.6},
        {"max_events": 3, "coverage_radius_km": 50, "equity_weight": 1},
    ]
    payloads = [client.post("/api/optimize", json=body).json() for body in bodies]
    assert calls == [(1, 0, 0), (2, 25, 0.6), (3, 50, 1)]
    assert all(payload["status"] == "optimal" for payload in payloads)
    assert [payload["total_events"] for payload in payloads] == [1, 2, 3]
    assert len({payload["modeled_outreach_coverage_objective"] for payload in payloads}) == 3
    assert len({tuple(row["municipality_id"] for row in payload["selected_locations"]) for payload in payloads}) == 3


def test_condition_specific_optimization_fails_honestly_with_or_without_export(
    tmp_path: Path,
) -> None:
    missing = client_for(GeographyRuntime(site_export_path=tmp_path / "missing.json"))
    body = {"max_events": 1, "coverage_radius_km": 25, "equity_weight": 0.5, "condition": "Cancer"}
    unavailable = missing.post("/api/optimize", json=body)
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "CLINICAL_SITE_EXPORT_UNAVAILABLE"

    path = tmp_path / "sites.json"
    path.write_text("[]", encoding="utf-8")
    available = client_for(GeographyRuntime(site_export_path=path)).post(
        "/api/optimize", json=body
    )
    assert available.status_code == 409
    assert available.json()["detail"]["code"] == "CONDITION_SPECIFIC_OPTIMIZATION_UNSUPPORTED"
    assert "no validated condition-specific access-gap term" in available.json()["detail"]["message"]


def test_official_aggregate_snapshot_is_complete_aligned_and_atomically_reloadable(tmp_path: Path) -> None:
    snapshot = load_aggregate_snapshot()
    assert snapshot.report.complete is True
    assert snapshot.report.unique_accepted_count == 2604
    assert len(snapshot.municipalities) == 187
    assert sum(row.block_group_count for row in snapshot.municipalities) == 2604
    first = tmp_path / "aggregates.json"
    second = tmp_path / "aggregates-2.json"
    assert save_aggregate_snapshot(snapshot, first) == save_aggregate_snapshot(snapshot, second)
    assert first.read_bytes() == second.read_bytes()
    assert load_aggregate_snapshot(first) == snapshot
    assert not list(tmp_path.glob("*.tmp"))


def test_access_summary_counts_same_final_population_and_quarantines_non_us_ma(tmp_path: Path) -> None:
    base = {
        "conditions": ["Cancer"], "city": "Boston", "state": "MA", "country": "US",
        "latitude": 42.32, "longitude": -71.09, "coordinate_status": "source_coordinates",
        "source_url": "https://example.test/site",
    }
    path = tmp_path / "sites.json"
    path.write_text(json.dumps([
        {**base, "nct_id": "NCT1", "facility_name": "Recruiting", "recruiting_status": "Recruiting"},
        {**base, "nct_id": "NCT2", "facility_name": "Completed", "recruiting_status": "Completed"},
        {**base, "nct_id": "NCT3", "facility_name": "Contradictory Country", "country": "Canada", "recruiting_status": "Recruiting"},
    ]), encoding="utf-8")
    loaded = load_trial_site_export(path)
    assert loaded.report.input_count == 3
    assert loaded.report.accepted_count == 2
    assert loaded.report.quarantined_count == 1
    assert "country as United States" in loaded.report.quarantine_reasons[0]

    response = client_for(GeographyRuntime(site_export_path=path)).get(
        "/api/geo", params={"municipality": "Boston", "condition": "Cancer"}
    )
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["clinical_site_accepted_count"] == 1
    assert summary["clinical_site_resolved_count"] == 1
    assert summary["clinical_site_unresolved_count"] == 0
    assert summary["clinical_site_deduplicated_count"] == 1
    assert summary["clinical_site_quarantined_count"] == 1


def _site_export_metadata(record_count: int) -> dict[str, Any]:
    return {
        "schema_version": "trialmatch_ma_trial_sites_v1",
        "generated_at": "2026-10-24T18:45:22Z",
        "cohort_selection": "Deterministic synthetic test cohort",
        "source": "Synthetic clinical export fixture",
        "source_snapshot_study_count": record_count,
        "expanded_study_count": record_count,
        "expanded_studies_with_ma_recruiting_sites": record_count,
        "source_location_count": record_count,
        "explicit_massachusetts_location_count": record_count,
        "excluded_non_recruiting_or_unknown_site_status_count": 0,
        "excluded_missing_facility_name_count": 0,
        "duplicate_record_count": 0,
        "exported_record_count": record_count,
        "exported_study_count": record_count,
        "unique_facility_location_count": record_count,
        "resolved_coordinate_count": record_count,
        "unresolved_coordinate_count": 0,
        "invalid_source_coordinate_count": 0,
        "earliest_retrieved_at": "2026-10-24T17:00:00Z",
        "latest_retrieved_at": "2026-10-24T18:00:00Z",
        "deduplication_key": "synthetic fixture key",
        "limitations": [
            "coordinate_status verified means a valid source pair, not an independently verified facility entrance."
        ],
    }


def test_versioned_envelope_prefers_geography_records_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    source_record = {
        "nct_id": "NCT-SOURCE",
        "conditions": ["Wrong projection"],
        "facility_name": "Wrong projection",
        "state": "MA",
        "country": "US",
    }
    geography_record = {
        "nct_id": "NCT-GEO",
        "conditions": ["Cancer"],
        "facility_source_id": "facility-1",
        "facility_name": "Source Pair Site",
        "city": "Boston",
        "state": "Massachusetts",
        "postal_code": "02108",
        "country": "United States",
        "latitude": 42.36,
        "longitude": -71.06,
        "coordinate_status": "verified",
        "coordinate_source": "ClinicalTrials.gov API v2 geoPoint",
        "coordinate_source_reference": "https://clinicaltrials.gov/data-api/api",
        "overall_status": "RECRUITING",
        "source_url": "https://clinicaltrials.gov/study/NCT-GEO",
        "retrieved_at": "2026-10-24T17:30:00Z",
    }
    path = tmp_path / "versioned-sites.json"
    path.write_text(
        json.dumps(
            {
                "metadata": _site_export_metadata(1),
                "records": [source_record],
                "geography_records": [geography_record],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_trial_site_export(path)
    assert loaded.report.record_collection == "geography_records"
    assert loaded.report.input_count == loaded.report.accepted_count == 1
    assert loaded.report.quarantined_count == 0
    assert loaded.sites[0].nct_id == "NCT-GEO"
    assert loaded.sites[0].resolution_status == "source_coordinates"
    assert loaded.sites[0].coordinate_source == "ClinicalTrials.gov API v2 geoPoint"
    assert loaded.report.metadata is not None
    assert loaded.report.metadata.cohort_selection == "Deterministic synthetic test cohort"
    assert "not an independently verified" in loaded.report.metadata.limitations[0]


def test_site_features_all_sites_exact_condition_and_available_zero_semantics(
    tmp_path: Path,
) -> None:
    base = {
        "city": "Boston",
        "state": "MA",
        "postal_code": "02108",
        "country": "US",
        "overall_status": "RECRUITING",
        "source_url": "https://example.test/study",
        "retrieved_at": "2026-10-24T17:30:00Z",
    }
    records = [
        {
            **base,
            "nct_id": "NCT1",
            "conditions": ["Cancer"],
            "facility_name": "Resolved Cancer Site",
            "latitude": 42.321809755146745,
            "longitude": -71.09124969447807,
            "coordinate_status": "verified",
            "coordinate_source": "ClinicalTrials.gov API v2 geoPoint",
            "coordinate_source_reference": "https://clinicaltrials.gov/data-api/api",
        },
        {
            **base,
            "nct_id": "NCT2",
            "conditions": ["  Cancer  "],
            "facility_name": "Unresolved Cancer Site",
            "coordinate_status": "unresolved",
        },
        {
            **base,
            "nct_id": "NCT3",
            "conditions": ["Lung Cancer"],
            "facility_name": "Different Exact Condition",
            "latitude": 42.4,
            "longitude": -71.1,
            "coordinate_status": "verified",
            "coordinate_source": "ClinicalTrials.gov API v2 geoPoint",
            "coordinate_source_reference": "https://clinicaltrials.gov/data-api/api",
        },
    ]
    path = tmp_path / "sites.json"
    path.write_text(json.dumps({"geography_records": records}), encoding="utf-8")
    client = client_for(GeographyRuntime(site_export_path=path))

    unfiltered = client.get("/api/geo", params={"municipality": "Boston"}).json()
    assert len(unfiltered["recruiting_site_features"]) == 3
    assert unfiltered["available_conditions"] == ["Cancer", "Lung Cancer"]

    exact = client.get(
        "/api/geo",
        params={"municipality": "Boston", "condition": "ＣＡＮＣＥＲ", "access_radius_km": 5},
    ).json()
    assert [feature["properties"]["nct_id"] for feature in exact["recruiting_site_features"]] == [
        "NCT1",
        "NCT2",
    ]
    assert exact["recruiting_site_features"][1]["geometry"] is None
    assert exact["summary"]["clinical_site_resolved_count"] == 1
    assert exact["summary"]["clinical_site_unresolved_count"] == 1
    assert exact["summary"]["clinical_site_distinct_nct_count"] == 2

    no_match = client.get(
        "/api/geo",
        params={"municipality": "Boston", "condition": "Cancer synonym", "access_radius_km": 5},
    ).json()
    assert no_match["recruiting_site_features"] == []
    properties = no_match["features"][0]["properties"]
    assert properties["nearest_resolved_recruiting_site_distance_km"] is None
    assert properties["distinct_nearby_recruiting_nct_count"] == 0
    assert properties["access_radius_km"] == 5


@pytest.mark.skipif(
    not Path("/tmp/trialmatch-ma-trial-sites.json").is_file(),
    reason="temporary real clinical export is unavailable",
)
def test_real_export_loader_and_condition_geo_integration() -> None:
    path = Path("/tmp/trialmatch-ma-trial-sites.json")
    loaded = load_trial_site_export(path)
    adapted = adapt_trial_sites(loaded.sites)
    retained_ncts = {site.nct_id for site in adapted.sites}
    resolved = [site for site in adapted.sites if site.resolution_status == "source_coordinates"]
    conditions = sorted(
        {" ".join(value.split()) for site in adapted.sites for value in site.conditions},
        key=lambda value: (value.casefold(), value),
    )

    assert loaded.report.record_collection == "geography_records"
    assert loaded.report.input_count == 149
    assert loaded.report.accepted_count == 149
    assert loaded.report.quarantined_count == 0
    assert adapted.report.input_count == 149
    assert adapted.report.massachusetts_count == 149
    assert adapted.report.non_recruiting_or_unknown_count == 0
    assert adapted.report.deduplicated_count == 149
    assert adapted.report.duplicate_count == 0
    assert adapted.report.resolved_count == 149
    assert adapted.report.unresolved_count == 0
    assert len(retained_ncts) == 86
    assert len(resolved) == 149
    assert all(site.resolution_status != "unresolved" for site in adapted.sites)
    assert loaded.report.metadata is not None
    assert loaded.report.metadata.unique_facility_location_count == 72
    assert loaded.report.metadata.exported_record_count == len(loaded.sites)

    sample_condition = conditions[0]
    response = client_for(GeographyRuntime(site_export_path=path)).get(
        "/api/geo", params={"condition": sample_condition, "access_radius_km": 0}
    )
    assert response.status_code == 200
    payload = response.json()
    site_features = payload["recruiting_site_features"]
    assert site_features
    assert all(
        any(
            " ".join(condition.casefold().split())
            == " ".join(sample_condition.casefold().split())
            for condition in feature["properties"]["conditions"]
        )
        for feature in site_features
    )
    summary = payload["summary"]
    assert summary["clinical_site_source_record_count"] == 149
    assert summary["clinical_site_schema_accepted_count"] == 149
    assert summary["clinical_site_massachusetts_recruiting_retained_count"] == 149
    assert summary["clinical_site_retained_count"] == len(site_features)
    assert summary["clinical_site_distinct_nct_count"] == len(
        {feature["properties"]["nct_id"] for feature in site_features}
    )
    assert summary["clinical_site_resolved_count"] == len(site_features)
    assert summary["clinical_site_unresolved_count"] == 0
    assert summary["clinical_site_duplicate_removed_count"] == 0
    assert summary["clinical_site_quarantined_count"] == 0
    assert summary["clinical_site_unique_facility_location_count"] == 72
    access_properties = [feature["properties"] for feature in payload["features"]]
    assert all(value["access_radius_km"] == 0 for value in access_properties)
    assert all(value["nearest_resolved_recruiting_site_distance_km"] is not None for value in access_properties)
    assert any(value["distinct_nearby_recruiting_nct_count"] == 0 for value in access_properties)
