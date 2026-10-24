from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.geography.access import compute_access_indicators
from backend.app.geography.geometry import (
    MassGISGeometryService, aggregate_representative_points, load_snapshot,
    polygon_area_centroid, save_snapshot,
)
from backend.app.geography.models import (
    ArcGISAdvancedQueryCapabilities, ArcGISFeature, ArcGISField, ArcGISLayerMetadata,
    ArcGISQueryEnvelope, ArcGISSpatialReference, MunicipalityEJSubsetAggregate,
    MunicipalityRepresentativePoint, TrialSite,
)
from backend.app.geography.router import _selected_locations_with_explanations
from backend.app.geography.scenario import build_real_ej_scenario
from backend.app.geography.sites import adapt_trial_sites
from backend.app.optimizer import CandidateLocation, DemandCommunity, OptimizationScenario, optimize


def polygon(x: float, y: float) -> dict[str, Any]:
    return {"rings": [[[x, y], [x + .02, y], [x + .02, y + .02], [x, y + .02], [x, y]]]}


class FakeGeometryClient:
    layer_url = "https://example.test/MapServer/0"
    retry_count = 0

    def __init__(self, pages: list[ArcGISQueryEnvelope], count: int, *, centroid: bool = False) -> None:
        self.pages = pages
        self.count = count
        self.calls: list[dict[str, Any]] = []
        self.metadata = ArcGISLayerMetadata(
            objectIdField="OBJECTID", maxRecordCount=2,
            spatialReference=ArcGISSpatialReference(wkid=26986, latestWkid=26986),
            fields=[ArcGISField(name=name, type="esriFieldTypeString") for name in ("OBJECTID", "MUNICIPALITY", "TOTAL_POP")],
            advancedQueryCapabilities=ArcGISAdvancedQueryCapabilities(supportsOrderBy=True, supportsReturningGeometryCentroid=centroid),
        )

    def get_metadata(self) -> ArcGISLayerMetadata:
        return self.metadata

    def get_count(self, where: str) -> int:
        return self.count

    def query_page(self, params: dict[str, Any]) -> ArcGISQueryEnvelope:
        self.calls.append(params)
        return self.pages[len(self.calls) - 1]


def feature(oid: int, municipality: str, population: int | None, *, geometry: Any = None, centroid: Any = None) -> ArcGISFeature:
    return ArcGISFeature(attributes={"OBJECTID": oid, "MUNICIPALITY": municipality, "TOTAL_POP": population}, geometry=geometry, centroid=centroid)


def page(*features: ArcGISFeature, exceeded: bool = False) -> ArcGISQueryEnvelope:
    return ArcGISQueryEnvelope(features=list(features), exceededTransferLimit=exceeded, spatialReference=ArcGISSpatialReference(wkid=4326))


def point(name: str, lat: float | None, lon: float | None) -> MunicipalityRepresentativePoint:
    resolved = lat is not None
    return MunicipalityRepresentativePoint(
        municipality=name, latitude=lat, longitude=lon,
        resolution_status="resolved" if resolved else "unresolved",
        point_method="population_weighted_mean_of_ej_block_group_points" if resolved else "unresolved_no_valid_geometry",
        block_group_source_count=1, valid_geometry_count=int(resolved),
        missing_geometry_count=int(not resolved), invalid_geometry_count=0,
        represented_population=100 if resolved else 0, source_ids=(name,),
    )


def aggregate(name: str, population: int | None = 100, english: float | None = 10) -> MunicipalityEJSubsetAggregate:
    return MunicipalityEJSubsetAggregate(
        municipality=name, block_group_count=1, source_ids=(name,),
        total_population_ej_subset=population, total_population_missing_count=int(population is None),
        percent_minority_population_weighted_ej_subset=20, percent_minority_represented_population=population or 0,
        percent_minority_missing_count=0, limited_english_population_weighted_ej_subset=english,
        limited_english_represented_population=population or 0, limited_english_missing_count=int(english is None),
        block_group_median_household_income_population_weighted_mean_usd_ej_subset=50000,
        income_represented_population=population or 0, income_missing_count=0,
    )


def site(nct: str, facility: str, *, source_id: str | None = None, state: str = "MA", lat: float | None = 42.36, lon: float | None = -71.06, conditions: tuple[str, ...] = ("Cancer",), status: str | None = "RECRUITING") -> TrialSite:
    resolved = lat is not None
    return TrialSite(
        nct_id=nct, conditions=conditions, facility_source_id=source_id, facility_name=facility,
        city="Boston", state=state, postal_code="02108", country="US", latitude=lat, longitude=lon,
        coordinate_source="synthetic_test_fixture" if resolved else None,
        coordinate_source_reference="synthetic_test_fixture" if resolved else None,
        resolution_status="source_coordinates" if resolved else "unresolved",
        overall_status=status,
        source_url="https://example.test", retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def test_polygon_centroid_validates_structure_ranges_and_crs_request() -> None:
    assert polygon_area_centroid(polygon(-71, 42)) == pytest.approx((42.01, -70.99))
    assert polygon_area_centroid({"rings": [[[-200, 42], [-199, 42], [-200, 42]]]}) is None
    client = FakeGeometryClient([page(feature(1, "Boston", 100, geometry=polygon(-71, 42)))], 1)
    snapshot = MassGISGeometryService(client, page_size=9).acquire()  # type: ignore[arg-type]
    assert client.calls[0]["outSR"] == 4326
    assert client.calls[0]["returnGeometry"] == "true"
    assert snapshot.report.source_crs == "EPSG:26986"
    assert snapshot.report.requested_output_crs == "EPSG:4326"
    assert snapshot.report.polygon_centroid_count == 1


def test_server_centroid_is_preferred_when_officially_supported() -> None:
    client = FakeGeometryClient([page(feature(1, "Boston", 1, geometry=polygon(-71, 42), centroid={"x": -70.5, "y": 42.5}))], 1, centroid=True)
    snapshot = MassGISGeometryService(client).acquire()  # type: ignore[arg-type]
    assert client.calls[0]["returnCentroid"] == "true"
    assert snapshot.report.arcgis_centroid_count == 1
    assert snapshot.municipalities[0].latitude == 42.5


def test_geometry_pagination_duplicate_missing_and_invalid_are_explicit() -> None:
    client = FakeGeometryClient([
        page(feature(1, "Boston", 100, geometry=polygon(-71, 42)), feature(2, "Boston", 0), exceeded=True),
        page(feature(2, "Boston", 0), feature(3, "Adams", 1, geometry={"rings": []})),
    ], 4)
    snapshot = MassGISGeometryService(client).acquire()  # type: ignore[arg-type]
    assert [call["resultOffset"] for call in client.calls] == [0, 2]
    assert snapshot.report.fetched_record_count == 4
    assert snapshot.report.duplicate_count == 1
    assert snapshot.report.missing_geometry_count == 1
    assert snapshot.report.invalid_geometry_count == 1
    assert snapshot.report.complete is False
    assert snapshot.report.resolved_municipality_count == 1
    assert snapshot.report.unresolved_municipality_count == 1


def test_population_weighted_point_and_zero_population_fallback() -> None:
    results = aggregate_representative_points([
        ("1", "Boston", 100, (42.0, -71.0), "valid"),
        ("2", "Boston", 300, (43.0, -70.0), "valid"),
        ("3", "Adams", 0, (42.0, -73.0), "valid"),
        ("4", "Adams", None, (44.0, -71.0), "valid"),
    ])
    adams, boston = results
    assert (boston.latitude, boston.longitude) == pytest.approx((42.75, -70.25))
    assert boston.represented_population == 400
    assert (adams.latitude, adams.longitude) == pytest.approx((43, -72))
    assert "unweighted_mean_fallback" in adams.point_method


def test_snapshot_is_canonical_atomic_and_reloadable(tmp_path: Path) -> None:
    snapshot = MassGISGeometryService(FakeGeometryClient([page(feature(1, "Boston", 1, geometry=polygon(-71, 42)))], 1)).acquire()  # type: ignore[arg-type]
    first = tmp_path / "points.json"
    second = tmp_path / "points2.json"
    assert save_snapshot(snapshot, first) == save_snapshot(snapshot, second)
    assert first.read_bytes() == second.read_bytes()
    assert load_snapshot(first) == snapshot
    assert not list(tmp_path.glob("*.tmp"))


def test_site_validation_massachusetts_deduplication_and_condition_filtering() -> None:
    with pytest.raises(ValidationError, match="present together"):
        TrialSite.model_validate({**site("NCT1", "Bad").model_dump(), "longitude": None})
    rows = (site("NCT1", "A", source_id="stable"), site("NCT1", "Duplicate", source_id="stable"), site("NCT5", "Same facility, distinct study", source_id="stable"), site("NCT2", "B", state="Massachusetts", conditions=("cAnCeR",)), site("NCT3", "C", state="RI"), site("NCT4", "D", lat=None, lon=None), site("NCT6", "Closed", status="COMPLETED"))
    adapted = adapt_trial_sites(rows, condition="CANCER")
    assert [item.nct_id for item in adapted.sites] == ["NCT1", "NCT2", "NCT4", "NCT5"]
    assert adapted.report.input_count == 7
    assert adapted.report.out_of_state_count == 1
    assert adapted.report.non_recruiting_or_unknown_count == 1
    assert adapted.report.duplicate_count == 1
    assert adapted.report.resolved_count == 3
    assert adapted.report.unresolved_count == 1


def test_access_nearest_distinct_nct_and_no_facility_double_count() -> None:
    municipality = point("Boston", 42.36, -71.06)
    rows = (site("NCT1", "A", source_id="1"), site("NCT1", "B", source_id="2", lat=42.361), site("NCT2", "C", source_id="3", lat=43), site("NCT3", "D", source_id="4", lat=None, lon=None))
    result = compute_access_indicators((municipality,), rows, radius_km=5, condition="cancer")[0]
    assert result.nearest_resolved_recruiting_site_distance_km == pytest.approx(0)
    assert result.distinct_nearby_nct_count == 1
    assert result.total_site_count == 4
    assert result.resolved_site_count == 3
    assert result.unresolved_site_count == 1
    assert result.municipality_resolution_status == "resolved"
    assert result.spatial_analysis_available is True
    assert "straight-line" in result.distance_limitation


def test_scenario_construction_reports_exclusions_and_runs_optimizer() -> None:
    aggregates = (aggregate("A", 100, 5), aggregate("B", None, 10), aggregate("C", 50, None), aggregate("D", 75, 20))
    points = (point("A", 42, -71), point("B", 42.1, -71), point("C", 42.2, -71), point("D", None, None))
    scenario, report = build_real_ej_scenario(
        aggregates, points, budget=1.0, max_events=1, coverage_radius_km=25,
        equity_weight_lambda=.6, event_cost=1.0, point_source="synthetic_test_fixture",
    )
    assert len(scenario.candidates) == len(scenario.communities) == 1
    assert report.included_municipality_count == 1
    assert report.excluded_null_population_count == 1
    assert report.excluded_missing_equity_indicator_count == 1
    assert report.excluded_unresolved_point_count == 1
    assert "abstract event units" in report.event_cost_assumption
    assert scenario.cost_unit == "abstract_equal_event_units"
    assert all(candidate.cost_unit == "abstract_equal_event_units" for candidate in scenario.candidates)
    result = optimize(scenario)
    assert result.status == "optimal"
    assert result.selected_municipality_ids == ("A",)
    assert result.modeled_ej_subset_population_proxy_covered == 100


def test_unresolved_municipality_is_explicitly_unavailable_for_spatial_access() -> None:
    result = compute_access_indicators(
        (point("Unknown", None, None),),
        (site("NCT1", "A", source_id="1"),),
        radius_km=25,
    )[0]
    assert result.municipality_resolution_status == "unresolved"
    assert result.spatial_analysis_available is False
    assert result.nearest_resolved_recruiting_site_distance_km is None
    assert result.distinct_nearby_nct_count == 0


def test_selected_location_explanations_use_union_overlap_and_fixed_plan_loss() -> None:
    located = {
        "latitude": 42.0,
        "coordinate_source": "synthetic_test_fixture",
        "coordinate_source_reference": "known-overlap-test",
    }
    scenario = OptimizationScenario(
        candidates=(
            CandidateLocation(
                candidate_id="A", longitude=0.0, event_cost=1.0,
                cost_unit="abstract_equal_event_units", **located,
            ),
            CandidateLocation(
                candidate_id="B", longitude=0.2, event_cost=1.0,
                cost_unit="abstract_equal_event_units", **located,
            ),
        ),
        communities=(
            DemandCommunity(
                community_id="Only A", longitude=-0.1,
                ej_subset_population_proxy=100, equity_priority=0.2, **located,
            ),
            DemandCommunity(
                community_id="Shared", longitude=0.1,
                ej_subset_population_proxy=200, equity_priority=0.5, **located,
            ),
            DemandCommunity(
                community_id="Only B", longitude=0.3,
                ej_subset_population_proxy=300, equity_priority=0.8, **located,
            ),
        ),
        budget=2.0,
        max_events=2,
        coverage_radius_km=20.0,
        equity_weight_lambda=0.5,
        cost_unit="abstract_equal_event_units",
    )

    selected = _selected_locations_with_explanations(
        scenario,
        ("A", "B"),
        (aggregate("A", 10, 5), aggregate("B", 20, 15)),
    )
    by_id = {location.municipality_id: location.explanation for location in selected}

    assert by_id["A"].raw_catchment_community_ids == ("Only A", "Shared")
    assert by_id["A"].raw_catchment_community_count == 2
    assert by_id["A"].raw_catchment_ej_subset_population_proxy == 300
    assert by_id["A"].raw_catchment_objective == pytest.approx(210)
    assert by_id["A"].uniquely_covered_community_ids == ("Only A",)
    assert by_id["A"].uniquely_covered_ej_subset_population_proxy == 100
    assert by_id["A"].uniquely_covered_objective == pytest.approx(60)
    assert by_id["A"].leave_one_out_objective_loss == pytest.approx(60)

    assert by_id["B"].raw_catchment_community_ids == ("Only B", "Shared")
    assert by_id["B"].raw_catchment_ej_subset_population_proxy == 500
    assert by_id["B"].raw_catchment_objective == pytest.approx(420)
    assert by_id["B"].uniquely_covered_community_ids == ("Only B",)
    assert by_id["B"].uniquely_covered_ej_subset_population_proxy == 300
    assert by_id["B"].uniquely_covered_objective == pytest.approx(270)
    assert by_id["B"].leave_one_out_objective_loss == pytest.approx(270)

    # Shared coverage is present in both raw catchments but in neither unique/removal loss.
    assert sum(value.raw_catchment_objective for value in by_id.values()) == pytest.approx(630)
    assert sum(value.uniquely_covered_objective for value in by_id.values()) == pytest.approx(330)
    assert "not causal impact" in by_id["A"].leave_one_out_interpretation
    assert by_id["A"].selected_municipality_ej_subset_population == 10
    assert by_id["B"].selected_municipality_limited_english_household_percent_ej_subset == 15
