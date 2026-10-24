"""Functional, persisted-data geography and outreach optimization API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator

from backend.app.optimizer import BaselineResult, OptimizationResult, build_formulation, optimize
from backend.app.optimizer.models import ConstraintSatisfaction, OptimizationScenario, SolverDetails

from .access import compute_access_indicators
from .aggregate_snapshot import (
    DEFAULT_AGGREGATE_SNAPSHOT_PATH,
    MunicipalityAggregateSnapshot,
    load_aggregate_snapshot,
)
from .geometry import DEFAULT_SNAPSHOT_PATH, load_snapshot
from .models import (
    MunicipalityEJSubsetAggregate,
    MunicipalityPointSnapshot,
    ScenarioConstructionReport,
    StrictModel,
    TrialSite,
)
from .scenario import build_real_ej_scenario
from .sites import (
    SiteAdapterReport,
    SiteExportResult,
    adapt_trial_sites,
    available_site_conditions,
    configured_site_export_path,
    load_trial_site_export,
    site_deduplication_key,
    unique_facility_location_count,
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


SITE_COORDINATE_APPROXIMATION_WARNING = (
    "Source-supplied coordinates are valid coordinate pairs but are not independently "
    "verified facility entrances and may be approximate."
)


class RecruitingSiteFeatureProperties(StrictModel):
    nct_id: str
    facility: str
    facility_source_id: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    conditions: tuple[str, ...]
    recruiting_status: str | None
    coordinate_source: str | None
    coordinate_source_reference: str | None
    coordinate_resolution_status: Literal["source_coordinates", "verified_geocode", "unresolved"]
    source_url: str | None
    retrieved_at: datetime | None
    coordinate_approximation_warning: Literal[
        "Source-supplied coordinates are valid coordinate pairs but are not independently verified facility entrances and may be approximate."
    ] = SITE_COORDINATE_APPROXIMATION_WARNING


class RecruitingSiteFeature(StrictModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: GeoJSONPoint | None
    properties: RecruitingSiteFeatureProperties


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
    # Compatibility fields retain their existing post-filter meanings.
    clinical_site_accepted_count: int | None = Field(default=None, ge=0)
    clinical_site_resolved_count: int | None = Field(default=None, ge=0)
    clinical_site_unresolved_count: int | None = Field(default=None, ge=0)
    clinical_site_deduplicated_count: int | None = Field(default=None, ge=0)
    clinical_site_quarantined_count: int | None = Field(default=None, ge=0)
    clinical_site_source_record_count: int | None = Field(default=None, ge=0)
    clinical_site_schema_accepted_count: int | None = Field(default=None, ge=0)
    clinical_site_massachusetts_recruiting_retained_count: int | None = Field(default=None, ge=0)
    clinical_site_retained_count: int | None = Field(default=None, ge=0)
    clinical_site_distinct_nct_count: int | None = Field(default=None, ge=0)
    clinical_site_duplicate_removed_count: int | None = Field(default=None, ge=0)
    clinical_site_unique_facility_location_count: int | None = Field(default=None, ge=0)
    clinical_site_source_location_count: int | None = Field(default=None, ge=0)
    clinical_site_source_snapshot_study_count: int | None = Field(default=None, ge=0)
    clinical_site_expanded_study_count: int | None = Field(default=None, ge=0)
    clinical_site_exported_study_count: int | None = Field(default=None, ge=0)
    clinical_site_export_generated_at: datetime | None = None
    clinical_site_export_scope: str | None = None
    clinical_site_export_limitations: tuple[str, ...] | None = None
    clinical_site_coordinate_precision_limitation: str | None = None


class GeoFeatureCollection(StrictModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: tuple[GeoFeature, ...]
    recruiting_site_features: tuple[RecruitingSiteFeature, ...] = ()
    available_conditions: tuple[str, ...] | None = None
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


class SelectedLocationExplanation(StrictModel):
    raw_catchment_community_ids: tuple[str, ...]
    raw_catchment_community_count: int = Field(ge=0)
    raw_catchment_ej_subset_population_proxy: int = Field(ge=0)
    raw_catchment_objective: float = Field(ge=0, allow_inf_nan=False)
    uniquely_covered_community_ids: tuple[str, ...]
    uniquely_covered_community_count: int = Field(ge=0)
    uniquely_covered_ej_subset_population_proxy: int = Field(ge=0)
    uniquely_covered_objective: float = Field(ge=0, allow_inf_nan=False)
    leave_one_out_objective_loss: float = Field(ge=0, allow_inf_nan=False)
    leave_one_out_interpretation: Literal[
        "fixed-plan removal loss; other selected locations remain fixed; not causal impact or reoptimized marginal value"
    ] = "fixed-plan removal loss; other selected locations remain fixed; not causal impact or reoptimized marginal value"
    selected_municipality_ej_subset_population: int = Field(ge=0)
    selected_municipality_limited_english_household_percent_ej_subset: float = Field(ge=0, le=100)
    selected_municipality_percent_minority_ej_subset: float | None = Field(default=None, ge=0, le=100)


class SelectedLocation(StrictModel):
    municipality_id: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    explanation: SelectedLocationExplanation


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


def _site_feature_id(site: TrialSite) -> str:
    digest = sha256("\x1f".join(site_deduplication_key(site)).encode("utf-8")).hexdigest()
    return f"recruiting-site-{digest[:20]}"


def _site_features(sites: tuple[TrialSite, ...]) -> tuple[RecruitingSiteFeature, ...]:
    return tuple(
        RecruitingSiteFeature(
            id=_site_feature_id(site),
            geometry=(
                GeoJSONPoint(coordinates=(site.longitude, site.latitude))
                if site.longitude is not None and site.latitude is not None
                else None
            ),
            properties=RecruitingSiteFeatureProperties(
                nct_id=site.nct_id,
                facility=site.facility_name,
                facility_source_id=site.facility_source_id,
                city=site.city,
                state=site.state,
                postal_code=site.postal_code,
                country=site.country,
                conditions=site.conditions,
                recruiting_status=site.overall_status,
                coordinate_source=site.coordinate_source,
                coordinate_source_reference=site.coordinate_source_reference,
                coordinate_resolution_status=site.resolution_status,
                source_url=site.source_url,
                retrieved_at=site.retrieved_at,
            ),
        )
        for site in sites
    )


def _selected_locations_with_explanations(
    scenario: OptimizationScenario,
    selected_ids: tuple[str, ...],
    aggregates: tuple[MunicipalityEJSubsetAggregate, ...],
) -> tuple[SelectedLocation, ...]:
    if not selected_ids:
        return ()
    formulation = build_formulation(scenario)
    candidate_by_id = {candidate.candidate_id: candidate for candidate in scenario.candidates}
    aggregate_by_id = {aggregate.municipality: aggregate for aggregate in aggregates}
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(formulation.candidate_ids)
    }
    selected_indices = tuple(candidate_index_by_id[candidate_id] for candidate_id in selected_ids)
    multiplicities = tuple(
        sum(int(formulation.coverage_matrix[row_index, column]) for column in selected_indices)
        for row_index in range(formulation.community_count)
    )
    full_plan_objective = float(
        sum(
            formulation.community_weights[index]
            for index, multiplicity in enumerate(multiplicities)
            if multiplicity > 0
        )
    )

    selected_locations: list[SelectedLocation] = []
    for municipality_id in selected_ids:
        selected_index = candidate_index_by_id[municipality_id]
        raw_indices = tuple(
            index
            for index in range(formulation.community_count)
            if formulation.coverage_matrix[index, selected_index]
        )
        unique_indices = tuple(index for index in raw_indices if multiplicities[index] == 1)
        objective_without_location = float(
            sum(
                formulation.community_weights[index]
                for index, multiplicity in enumerate(multiplicities)
                if multiplicity - int(formulation.coverage_matrix[index, selected_index]) > 0
            )
        )
        aggregate = aggregate_by_id[municipality_id]
        candidate = candidate_by_id[municipality_id]
        assert aggregate.total_population_ej_subset is not None
        assert aggregate.limited_english_population_weighted_ej_subset is not None
        selected_locations.append(
            SelectedLocation(
                municipality_id=municipality_id,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                explanation=SelectedLocationExplanation(
                    raw_catchment_community_ids=tuple(
                        formulation.community_ids[index] for index in raw_indices
                    ),
                    raw_catchment_community_count=len(raw_indices),
                    raw_catchment_ej_subset_population_proxy=int(
                        sum(formulation.community_populations[index] for index in raw_indices)
                    ),
                    raw_catchment_objective=float(
                        sum(formulation.community_weights[index] for index in raw_indices)
                    ),
                    uniquely_covered_community_ids=tuple(
                        formulation.community_ids[index] for index in unique_indices
                    ),
                    uniquely_covered_community_count=len(unique_indices),
                    uniquely_covered_ej_subset_population_proxy=int(
                        sum(formulation.community_populations[index] for index in unique_indices)
                    ),
                    uniquely_covered_objective=float(
                        sum(formulation.community_weights[index] for index in unique_indices)
                    ),
                    leave_one_out_objective_loss=max(
                        0.0, full_plan_objective - objective_without_location
                    ),
                    selected_municipality_ej_subset_population=(
                        aggregate.total_population_ej_subset
                    ),
                    selected_municipality_limited_english_household_percent_ej_subset=(
                        aggregate.limited_english_population_weighted_ej_subset
                    ),
                    selected_municipality_percent_minority_ej_subset=(
                        aggregate.percent_minority_population_weighted_ej_subset
                    ),
                ),
            )
        )
    return tuple(selected_locations)


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
    catalog_report: SiteAdapterReport | None = None
    recruiting_site_features: tuple[RecruitingSiteFeature, ...] = ()
    available_conditions: tuple[str, ...] | None = None
    all_retained_sites: tuple[TrialSite, ...] = ()
    access_by_name = {}
    if sites.report.available:
        catalog_adapted = adapt_trial_sites(sites.sites)
        all_retained_sites = catalog_adapted.sites
        catalog_report = catalog_adapted.report
        available_conditions = available_site_conditions(catalog_adapted.sites)
        adapted = adapt_trial_sites(sites.sites, condition=normalized_condition)
        adapted_report = adapted.report
        recruiting_site_features = _site_features(adapted.sites)
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
    export_metadata = sites.report.metadata
    export_limitations = (
        export_metadata.limitations
        if export_metadata is not None
        else (
            "Producer cohort scope metadata was not supplied with this clinical-site export.",
            SITE_COORDINATE_APPROXIMATION_WARNING,
        )
        if sites.report.available
        else None
    )
    return GeoFeatureCollection(
        features=tuple(features),
        recruiting_site_features=recruiting_site_features,
        available_conditions=available_conditions,
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
            clinical_site_source_record_count=sites.report.input_count,
            clinical_site_schema_accepted_count=sites.report.accepted_count,
            clinical_site_massachusetts_recruiting_retained_count=(
                catalog_report.deduplicated_count if catalog_report else None
            ),
            clinical_site_retained_count=(
                adapted_report.deduplicated_count if adapted_report else None
            ),
            clinical_site_distinct_nct_count=(
                len({site.nct_id.casefold() for site in adapted.sites})
                if adapted_report is not None
                else None
            ),
            clinical_site_duplicate_removed_count=(
                adapted_report.duplicate_count if adapted_report else None
            ),
            clinical_site_unique_facility_location_count=(
                export_metadata.unique_facility_location_count
                if export_metadata is not None
                else unique_facility_location_count(all_retained_sites)
                if sites.report.available
                else None
            ),
            clinical_site_source_location_count=(
                export_metadata.source_location_count if export_metadata else None
            ),
            clinical_site_source_snapshot_study_count=(
                export_metadata.source_snapshot_study_count if export_metadata else None
            ),
            clinical_site_expanded_study_count=(
                export_metadata.expanded_study_count if export_metadata else None
            ),
            clinical_site_exported_study_count=(
                export_metadata.exported_study_count if export_metadata else None
            ),
            clinical_site_export_generated_at=(
                export_metadata.generated_at if export_metadata else None
            ),
            clinical_site_export_scope=(
                export_metadata.cohort_selection
                if export_metadata is not None
                else "Loaded external clinical-site export; producer cohort scope metadata was not supplied."
                if sites.report.available
                else None
            ),
            clinical_site_export_limitations=export_limitations,
            clinical_site_coordinate_precision_limitation=(
                SITE_COORDINATE_APPROXIMATION_WARNING if sites.report.available else None
            ),
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
    selected = _selected_locations_with_explanations(
        scenario,
        result.selected_municipality_ids,
        aggregates_snapshot.municipalities,
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
