"""Functional, persisted-data geography and outreach optimization API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator

from backend.app.optimizer import BaselineResult, OptimizationResult, optimize
from backend.app.optimizer.models import ConstraintSatisfaction, SolverDetails

from .access import compute_access_indicators
from .aggregate_snapshot import (
    DEFAULT_AGGREGATE_SNAPSHOT_PATH,
    MunicipalityAggregateSnapshot,
    load_aggregate_snapshot,
)
from .geometry import DEFAULT_SNAPSHOT_PATH, load_snapshot
from .models import (
    MunicipalityPointSnapshot,
    ScenarioConstructionReport,
    StrictModel,
)
from .scenario import build_real_ej_scenario
from .sites import (
    SiteAdapterReport,
    SiteExportResult,
    adapt_trial_sites,
    configured_site_export_path,
    load_trial_site_export,
)


class GeoJSONPoint(StrictModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class GeoFeatureProperties(StrictModel):
    municipality: str
    source_scope: Literal[
        "EJ-flagged-block-group subset; not full municipality statistics"
    ]
    ej_subset_population: int | None
    population_unit: Literal["persons"]
    population_weighted_percent_minority_ej_subset: float | None
    population_weighted_limited_english_household_percent_ej_subset: float | None
    percent_unit: Literal["percentage_points_0_to_100"]
    population_weighted_mean_block_group_median_household_income_usd_ej_subset: float | None
    income_statistic_label: Literal[
        "population-weighted mean of block-group medians; not a municipality median"
    ]
    ej_block_group_count: int
    coordinate_resolution_status: Literal["resolved", "unresolved"]
    coordinate_method: str
    nearest_resolved_recruiting_site_distance_km: float | None
    distinct_nearby_recruiting_nct_count: int | None
    access_radius_km: float | None
    access_distance_limitation: str | None


class GeoFeature(StrictModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: GeoJSONPoint | None
    properties: GeoFeatureProperties


class GeoSummary(StrictModel):
    observed_feature_count: int = Field(ge=0)
    resolved_feature_count: int = Field(ge=0)
    unresolved_feature_count: int = Field(ge=0)
    source_name: Literal["MassGIS Environmental Justice Populations 2020"] = (
        "MassGIS Environmental Justice Populations 2020"
    )
    source_url: str
    retrieved_at: datetime
    source_filter: Literal["EJ='Yes'"] = "EJ='Yes'"
    output_crs: Literal["EPSG:4326"] = "EPSG:4326"
    coordinate_method: str
    clinical_site_data_available: bool
    clinical_site_accepted_count: int | None = Field(default=None, ge=0)
    clinical_site_resolved_count: int | None = Field(default=None, ge=0)
    clinical_site_unresolved_count: int | None = Field(default=None, ge=0)
    clinical_site_deduplicated_count: int | None = Field(default=None, ge=0)
    clinical_site_quarantined_count: int | None = Field(default=None, ge=0)


class GeoFeatureCollection(StrictModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: tuple[GeoFeature, ...]
    summary: GeoSummary


class OptimizeRequest(StrictModel):
    max_events: int = Field(ge=0, le=20)
    coverage_radius_km: float = Field(ge=0, le=200, allow_inf_nan=False)
    equity_weight: float = Field(ge=0, le=1, allow_inf_nan=False)
    condition: str | None = Field(default=None, max_length=200)

    @field_validator("condition")
    @classmethod
    def condition_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("condition must not be blank")
        return value


class SelectedLocation(StrictModel):
    municipality_id: str
    latitude: float
    longitude: float


class OptimizationProvenance(StrictModel):
    source_name: Literal["MassGIS Environmental Justice Populations 2020"] = (
        "MassGIS Environmental Justice Populations 2020"
    )
    source_url: str
    source_filter: Literal["EJ='Yes'"] = "EJ='Yes'"
    aggregate_retrieved_at: datetime
    point_retrieved_at: datetime
    aggregate_source_record_count: int = Field(ge=0)
    municipality_aggregate_count: int = Field(ge=0)
    coordinate_crs: Literal["EPSG:4326"] = "EPSG:4326"
    coordinate_method: str
    runtime_massgis_fetch: Literal[False] = False


class OptimizeResponse(StrictModel):
    status: Literal["optimal", "feasible", "infeasible", "unbounded", "solver_error"]
    selected_locations: tuple[SelectedLocation, ...]
    covered_municipality_ids: tuple[str, ...]
    covered_municipality_count: int = Field(ge=0)
    modeled_outreach_coverage_objective: float = Field(ge=0, allow_inf_nan=False)
    modeled_ej_subset_population_proxy_covered: int = Field(ge=0)
    total_events: int = Field(ge=0)
    total_cost: float = Field(ge=0, allow_inf_nan=False)
    cost_unit: Literal["abstract_equal_event_units"]
    solver: SolverDetails
    baselines: tuple[BaselineResult, ...]
    constraint_satisfaction: ConstraintSatisfaction
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    scenario_construction: ScenarioConstructionReport
    provenance: OptimizationProvenance
    generated_at: datetime


@dataclass(frozen=True)
class GeographyRuntime:
    """Injectable file/solver boundary used by production and TestClient tests."""

    aggregate_snapshot_path: str | Path = DEFAULT_AGGREGATE_SNAPSHOT_PATH
    point_snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH
    site_export_path: str | Path | None = None
    optimizer: Callable[..., OptimizationResult] = optimize

    def load_aggregates(self) -> MunicipalityAggregateSnapshot:
        return load_aggregate_snapshot(self.aggregate_snapshot_path)

    def load_points(self) -> MunicipalityPointSnapshot:
        return load_snapshot(self.point_snapshot_path)

    def load_sites(self) -> SiteExportResult:
        return load_trial_site_export(
            self.site_export_path
            if self.site_export_path is not None
            else configured_site_export_path()
        )


_DEFAULT_RUNTIME = GeographyRuntime()


def get_geography_runtime() -> GeographyRuntime:
    return _DEFAULT_RUNTIME


def _condition_conflict(message: str, code: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def _load_persisted(runtime: GeographyRuntime) -> tuple[MunicipalityAggregateSnapshot, MunicipalityPointSnapshot]:
    try:
        return runtime.load_aggregates(), runtime.load_points()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "GEOGRAPHY_SNAPSHOT_UNAVAILABLE",
                "message": f"Persisted geography snapshot could not be loaded: {exc}",
            },
        ) from exc


def _load_sites(runtime: GeographyRuntime) -> SiteExportResult:
    try:
        return runtime.load_sites()
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CLINICAL_SITE_EXPORT_INVALID",
                "message": f"Clinical site export could not be loaded: {exc}",
            },
        ) from exc


geography_router = APIRouter(prefix="/api", tags=["geography"])


@geography_router.get("/geo", response_model=GeoFeatureCollection)
def get_geo(
    municipality: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    condition: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    access_radius_km: Annotated[float, Query(ge=0, le=200, allow_inf_nan=False)] = 25.0,
    runtime: GeographyRuntime = Depends(get_geography_runtime),
) -> GeoFeatureCollection:
    aggregates_snapshot, points_snapshot = _load_persisted(runtime)
    normalized_condition = condition.strip() if condition is not None else None
    if condition is not None and not normalized_condition:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "condition must not be blank"})
    sites = _load_sites(runtime)
    if normalized_condition is not None and not sites.report.available:
        raise _condition_conflict(
            "Condition-specific access requires a clinical site export, but none is available.",
            "CLINICAL_SITE_EXPORT_UNAVAILABLE",
        )

    adapted_report: SiteAdapterReport | None = None
    access_by_name = {}
    if sites.report.available:
        adapted = adapt_trial_sites(sites.sites, condition=normalized_condition)
        adapted_report = adapted.report
        access_by_name = {
            value.municipality: value
            for value in compute_access_indicators(
                points_snapshot.municipalities,
                sites.sites,
                radius_km=access_radius_km,
                condition=normalized_condition,
            )
        }

    point_by_name = {point.municipality: point for point in points_snapshot.municipalities}
    aggregate_rows = aggregates_snapshot.municipalities
    if municipality is not None:
        target = municipality.strip().casefold()
        aggregate_rows = tuple(
            row for row in aggregate_rows if row.municipality.casefold() == target
        )
    features: list[GeoFeature] = []
    for aggregate in aggregate_rows:
        point = point_by_name.get(aggregate.municipality)
        if point is None:
            continue
        access = access_by_name.get(aggregate.municipality)
        geometry = (
            GeoJSONPoint(coordinates=(point.longitude, point.latitude))
            if point.longitude is not None and point.latitude is not None
            else None
        )
        features.append(
            GeoFeature(
                id=aggregate.municipality,
                geometry=geometry,
                properties=GeoFeatureProperties(
                    municipality=aggregate.municipality,
                    source_scope=aggregate.source_scope,
                    ej_subset_population=aggregate.total_population_ej_subset,
                    population_unit=aggregate.population_unit,
                    population_weighted_percent_minority_ej_subset=aggregate.percent_minority_population_weighted_ej_subset,
                    population_weighted_limited_english_household_percent_ej_subset=aggregate.limited_english_population_weighted_ej_subset,
                    percent_unit=aggregate.percent_unit,
                    population_weighted_mean_block_group_median_household_income_usd_ej_subset=aggregate.block_group_median_household_income_population_weighted_mean_usd_ej_subset,
                    income_statistic_label=aggregate.income_statistic_note,
                    ej_block_group_count=aggregate.block_group_count,
                    coordinate_resolution_status=point.resolution_status,
                    coordinate_method=point.point_method,
                    nearest_resolved_recruiting_site_distance_km=(
                        access.nearest_resolved_recruiting_site_distance_km if access else None
                    ),
                    distinct_nearby_recruiting_nct_count=(
                        access.distinct_nearby_nct_count if access else None
                    ),
                    access_radius_km=access_radius_km if access else None,
                    access_distance_limitation=access.distance_limitation if access else None,
                ),
            )
        )
    resolved_count = sum(feature.geometry is not None for feature in features)
    geometry_report = points_snapshot.report
    return GeoFeatureCollection(
        features=tuple(features),
        summary=GeoSummary(
            observed_feature_count=len(features),
            resolved_feature_count=resolved_count,
            unresolved_feature_count=len(features) - resolved_count,
            source_url=aggregates_snapshot.report.source_url,
            retrieved_at=aggregates_snapshot.report.finished_at_utc,
            coordinate_method=(
                f"{geometry_report.server_transformation_method}; municipality representative "
                "point derived from EJ block-group polygon centroids"
            ),
            clinical_site_data_available=sites.report.available,
            clinical_site_accepted_count=(adapted_report.deduplicated_count if adapted_report else None),
            clinical_site_resolved_count=(adapted_report.resolved_count if adapted_report else None),
            clinical_site_unresolved_count=(adapted_report.unresolved_count if adapted_report else None),
            clinical_site_deduplicated_count=(adapted_report.deduplicated_count if adapted_report else None),
            clinical_site_quarantined_count=sites.report.quarantined_count,
        ),
    )


@geography_router.post("/optimize", response_model=OptimizeResponse)
def post_optimize(
    request: OptimizeRequest,
    runtime: GeographyRuntime = Depends(get_geography_runtime),
) -> OptimizeResponse:
    aggregates_snapshot, points_snapshot = _load_persisted(runtime)
    if request.condition is not None:
        sites = _load_sites(runtime)
        if not sites.report.available:
            raise _condition_conflict(
                "Condition-specific optimization requires a clinical site export, but none is available.",
                "CLINICAL_SITE_EXPORT_UNAVAILABLE",
            )
        raise _condition_conflict(
            "Condition-specific optimization is unsupported because the current objective has no validated condition-specific access-gap term.",
            "CONDITION_SPECIFIC_OPTIMIZATION_UNSUPPORTED",
        )

    point_source = (
        f"{points_snapshot.report.source_layer_url}; acquired "
        f"{points_snapshot.report.acquisition_utc.isoformat()}"
    )
    scenario, construction = build_real_ej_scenario(
        aggregates_snapshot.municipalities,
        points_snapshot.municipalities,
        budget=float(request.max_events),
        max_events=request.max_events,
        coverage_radius_km=request.coverage_radius_km,
        equity_weight_lambda=request.equity_weight,
        event_cost=1.0,
        point_source=point_source,
    )
    result = runtime.optimizer(scenario)
    candidate_by_id = {candidate.candidate_id: candidate for candidate in scenario.candidates}
    selected = tuple(
        SelectedLocation(
            municipality_id=municipality_id,
            latitude=candidate_by_id[municipality_id].latitude,
            longitude=candidate_by_id[municipality_id].longitude,
        )
        for municipality_id in result.selected_municipality_ids
    )
    return OptimizeResponse(
        status=result.status,
        selected_locations=selected,
        covered_municipality_ids=result.covered_community_ids,
        covered_municipality_count=len(result.covered_community_ids),
        modeled_outreach_coverage_objective=result.modeled_outreach_coverage_objective,
        modeled_ej_subset_population_proxy_covered=result.modeled_ej_subset_population_proxy_covered,
        total_events=result.total_events,
        total_cost=result.total_cost,
        cost_unit=result.cost_unit,
        solver=result.solver,
        baselines=result.baselines,
        constraint_satisfaction=result.constraint_satisfaction,
        assumptions=result.assumptions + construction.assumptions,
        limitations=result.limitations
        + (
            "This API integrates persisted official representative coordinates; they are analytical points, not outreach venues.",
            "The objective is modeled EJ-subset coverage, not enrollment, eligibility, or a causal outcome.",
        ),
        scenario_construction=construction,
        provenance=OptimizationProvenance(
            source_url=aggregates_snapshot.report.source_url,
            aggregate_retrieved_at=aggregates_snapshot.report.finished_at_utc,
            point_retrieved_at=points_snapshot.report.acquisition_utc,
            aggregate_source_record_count=aggregates_snapshot.report.unique_accepted_count,
            municipality_aggregate_count=len(aggregates_snapshot.municipalities),
            coordinate_method=(
                f"{points_snapshot.report.server_transformation_method}; municipality representative "
                "point derived from EJ block-group polygon centroids"
            ),
        ),
        generated_at=datetime.now(timezone.utc),
    )
