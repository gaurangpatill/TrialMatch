"""Typed source, domain, provenance, and persistence-boundary models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PERCENT_UNIT = "percentage_points_0_to_100"
POPULATION_UNIT = "persons"
INCOME_UNIT = "usd_block_group_median_household_income"
EJ_SUBSET_LABEL = "EJ-flagged-block-group subset; not full municipality statistics"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArcGISField(BaseModel):
    """Field metadata used for discovery; ArcGIS may add descriptive keys."""

    model_config = ConfigDict(extra="allow")
    name: str
    type: str
    alias: str | None = None


class ArcGISAdvancedQueryCapabilities(BaseModel):
    model_config = ConfigDict(extra="allow")
    supportsPagination: bool | None = None
    supportsOrderBy: bool | None = None
    supportsReturningGeometryCentroid: bool | None = None


class ArcGISSpatialReference(BaseModel):
    model_config = ConfigDict(extra="allow")
    wkid: int | None = None
    latestWkid: int | None = None


class ArcGISPoint(StrictModel):
    x: float = Field(ge=-180, le=180, allow_inf_nan=False)
    y: float = Field(ge=-90, le=90, allow_inf_nan=False)
    spatialReference: ArcGISSpatialReference | None = None


class ArcGISPolygon(BaseModel):
    model_config = ConfigDict(extra="allow")
    rings: list[list[list[float]]]
    spatialReference: ArcGISSpatialReference | None = None


class ArcGISLayerMetadata(BaseModel):
    """Subset of layer metadata needed to construct deterministic queries."""

    model_config = ConfigDict(extra="allow")
    objectIdField: str | None = None
    objectIdFieldName: str | None = None
    maxRecordCount: int | None = Field(default=None, gt=0)
    fields: list[ArcGISField] = Field(default_factory=list)
    advancedQueryCapabilities: ArcGISAdvancedQueryCapabilities | None = None
    spatialReference: ArcGISSpatialReference | None = None

    @property
    def object_id_field(self) -> str | None:
        explicit = self.objectIdField or self.objectIdFieldName
        if explicit:
            return explicit
        return next(
            (field.name for field in self.fields if field.type == "esriFieldTypeOID"),
            None,
        )

    @property
    def supports_order_by(self) -> bool:
        capabilities = self.advancedQueryCapabilities
        return capabilities is None or capabilities.supportsOrderBy is not False


class ArcGISCountEnvelope(StrictModel):
    count: int = Field(ge=0)


class ArcGISError(StrictModel):
    code: int
    message: str
    details: list[str] = Field(default_factory=list)


class ArcGISFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attributes: dict[str, Any]
    geometry: dict[str, Any] | None = None
    centroid: dict[str, Any] | None = None


class ArcGISQueryEnvelope(BaseModel):
    """Validated query payload; additive ArcGIS response metadata is retained."""

    model_config = ConfigDict(extra="allow")
    features: list[ArcGISFeature]
    exceededTransferLimit: bool = False
    objectIdFieldName: str | None = None
    spatialReference: ArcGISSpatialReference | None = None


class RawEJAttributes(BaseModel):
    """Required MassGIS fields; present JSON nulls remain Python ``None``."""

    model_config = ConfigDict(extra="ignore")
    source_id: str
    MUNICIPALITY: str | None
    TOTAL_POP: int | None
    PCT_MINORITY: float | None
    LIMENGHHPCT: float | None
    BG_MHHI: float | None
    EJ: str | None
    EJ_CRIT_DESC: str | None

    @field_validator("source_id", mode="before")
    @classmethod
    def normalize_source_id(cls, value: Any) -> str:
        if value is None or isinstance(value, bool):
            raise ValueError("source object ID is required")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("source object ID is required")
        return normalized

    @field_validator("TOTAL_POP")
    @classmethod
    def validate_population(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("TOTAL_POP must be non-negative")
        return value

    @field_validator("PCT_MINORITY", "LIMENGHHPCT")
    @classmethod
    def validate_percent(cls, value: float | None) -> float | None:
        if value is not None and not 0 <= value <= 100:
            raise ValueError("percent must be in percentage points from 0 through 100")
        return value

    @field_validator("BG_MHHI")
    @classmethod
    def validate_income(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("BG_MHHI must be non-negative")
        return value


class NormalizedBlockGroup(StrictModel):
    """Aggregate community attributes; this model contains no patient data."""

    source_id: str
    municipality: str
    total_population: int | None = Field(ge=0)
    percent_minority: float | None = Field(ge=0, le=100)
    limited_english_household_percent: float | None = Field(ge=0, le=100)
    block_group_median_household_income_usd: float | None = Field(ge=0)
    ej_flag: Literal["Yes"]
    ej_criteria_description: str | None
    percent_unit: Literal["percentage_points_0_to_100"] = PERCENT_UNIT
    population_unit: Literal["persons"] = POPULATION_UNIT
    income_unit: Literal["usd_block_group_median_household_income"] = INCOME_UNIT
    geometry: None = None
    source_scope: Literal["aggregate_community_block_group"] = "aggregate_community_block_group"

    @field_validator("municipality")
    @classmethod
    def municipality_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("municipality is required")
        return value


class MunicipalityEJSubsetAggregate(StrictModel):
    municipality: str
    source_scope: Literal[
        "EJ-flagged-block-group subset; not full municipality statistics"
    ] = EJ_SUBSET_LABEL
    block_group_count: int = Field(ge=1)
    source_ids: tuple[str, ...]
    total_population_ej_subset: int | None = Field(ge=0)
    total_population_missing_count: int = Field(ge=0)
    percent_minority_population_weighted_ej_subset: float | None = Field(ge=0, le=100)
    percent_minority_represented_population: int = Field(ge=0)
    percent_minority_missing_count: int = Field(ge=0)
    limited_english_population_weighted_ej_subset: float | None = Field(ge=0, le=100)
    limited_english_represented_population: int = Field(ge=0)
    limited_english_missing_count: int = Field(ge=0)
    block_group_median_household_income_population_weighted_mean_usd_ej_subset: float | None = Field(ge=0)
    income_represented_population: int = Field(ge=0)
    income_missing_count: int = Field(ge=0)
    percent_unit: Literal["percentage_points_0_to_100"] = PERCENT_UNIT
    population_unit: Literal["persons"] = POPULATION_UNIT
    income_statistic_note: Literal[
        "population-weighted mean of block-group medians; not a municipality median"
    ] = "population-weighted mean of block-group medians; not a municipality median"


class QuarantinedRecord(StrictModel):
    page_offset: int = Field(ge=0)
    record_index: int = Field(ge=0)
    source_id: str | None = None
    reason: str


class AcquisitionReport(StrictModel):
    source_url: str
    where: Literal["EJ='Yes'"] = "EJ='Yes'"
    object_id_field: str | None
    out_fields: tuple[str, ...]
    page_size: int = Field(gt=0)
    started_at_utc: datetime
    finished_at_utc: datetime
    expected_source_count: int | None = Field(default=None, ge=0)
    fetched_record_count: int = Field(ge=0)
    unique_accepted_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    invalid_quarantined_count: int = Field(ge=0)
    page_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    complete: bool
    termination_reason: str
    query_parameters: dict[str, str | int | bool]
    schema_validated: bool = True
    missing_value_counts: dict[str, int] = Field(default_factory=dict)
    transformations: tuple[str, ...] = ()
    filters_and_exclusions: tuple[str, ...] = ()
    duplicate_source_ids: tuple[str, ...] = ()
    quarantined: tuple[QuarantinedRecord, ...] = ()
    partial_failures: tuple[str, ...] = ()
    raw_snapshot_sha256: str | None = None
    raw_snapshot_record_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def counts_reconcile(self) -> "AcquisitionReport":
        if self.unique_accepted_count + self.duplicate_count + self.invalid_quarantined_count != self.fetched_record_count:
            raise ValueError("fetched count must reconcile accepted, duplicate, and quarantined records")
        return self


class IngestionResult(StrictModel):
    records: tuple[RawEJAttributes, ...]
    report: AcquisitionReport


class NormalizationResult(StrictModel):
    records: tuple[NormalizedBlockGroup, ...]
    quarantined: tuple[QuarantinedRecord, ...]


class BlockGroupRepresentativePoint(StrictModel):
    source_id: str
    municipality: str
    total_population: int | None = Field(ge=0)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    point_method: Literal["arcgis_returned_centroid", "polygon_area_centroid"]


class MunicipalityRepresentativePoint(StrictModel):
    municipality: str
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    resolution_status: Literal["resolved", "unresolved"]
    point_method: Literal[
        "population_weighted_mean_of_ej_block_group_points",
        "unweighted_mean_fallback_zero_or_missing_population",
        "unresolved_no_valid_geometry",
    ]
    block_group_source_count: int = Field(ge=1)
    valid_geometry_count: int = Field(ge=0)
    missing_geometry_count: int = Field(ge=0)
    invalid_geometry_count: int = Field(ge=0)
    represented_population: int = Field(ge=0)
    source_ids: tuple[str, ...]

    @model_validator(mode="after")
    def coordinate_pair_matches_status(self) -> "MunicipalityRepresentativePoint":
        present = self.latitude is not None and self.longitude is not None
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("municipality latitude and longitude must be present together")
        if present != (self.resolution_status == "resolved"):
            raise ValueError("resolved status must match coordinate availability")
        return self


class GeometryAcquisitionReport(StrictModel):
    source_layer_url: str
    where: Literal["EJ='Yes'"] = "EJ='Yes'"
    source_crs: str
    requested_output_crs: Literal["EPSG:4326"] = "EPSG:4326"
    server_transformation_method: str
    acquisition_utc: datetime
    object_id_field: str
    query_parameters: dict[str, str | int | bool]
    expected_source_count: int = Field(ge=0)
    fetched_record_count: int = Field(ge=0)
    unique_source_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    page_count: int = Field(ge=0)
    complete: bool
    invalid_source_record_count: int = Field(ge=0)
    missing_geometry_count: int = Field(ge=0)
    invalid_geometry_count: int = Field(ge=0)
    arcgis_centroid_count: int = Field(ge=0)
    polygon_centroid_count: int = Field(ge=0)
    resolved_municipality_count: int = Field(ge=0)
    unresolved_municipality_count: int = Field(ge=0)
    limitations: tuple[str, ...]


class MunicipalityPointSnapshot(StrictModel):
    schema_version: Literal["municipality_ej_representative_points_v1"] = "municipality_ej_representative_points_v1"
    report: GeometryAcquisitionReport
    municipalities: tuple[MunicipalityRepresentativePoint, ...]


SiteResolutionStatus = Literal["source_coordinates", "verified_geocode", "unresolved"]


class TrialSite(StrictModel):
    """Strict clinical export adapter; never geocodes or infers coordinates."""

    nct_id: str
    conditions: tuple[str, ...] = ()
    facility_source_id: str | None = None
    facility_name: str
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    coordinate_source: str | None = None
    coordinate_source_reference: str | None = None
    resolution_status: SiteResolutionStatus = "unresolved"
    overall_status: str | None = None
    source_url: str | None = None
    retrieved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_location_resolution(self) -> "TrialSite":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be present together")
        resolved = self.resolution_status in {"source_coordinates", "verified_geocode"}
        if resolved and (self.latitude is None or not self.coordinate_source or not self.coordinate_source_reference):
            raise ValueError("resolved sites require coordinates and coordinate provenance")
        if not resolved and (self.latitude is not None or self.longitude is not None):
            raise ValueError("unresolved sites cannot provide analysis coordinates")
        if not self.nct_id.strip() or not self.facility_name.strip():
            raise ValueError("nct_id and facility_name must not be blank")
        return self


class SiteAdapterReport(StrictModel):
    input_count: int = Field(ge=0)
    massachusetts_count: int = Field(ge=0)
    out_of_state_count: int = Field(ge=0)
    non_recruiting_or_unknown_count: int = Field(ge=0)
    deduplicated_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    condition_filter: str | None = None
    deduplication_method: str


class SiteAdapterResult(StrictModel):
    sites: tuple[TrialSite, ...]
    report: SiteAdapterReport


class AccessIndicator(StrictModel):
    municipality: str
    municipality_resolution_status: Literal["resolved", "unresolved"]
    spatial_analysis_available: bool
    nearest_resolved_recruiting_site_distance_km: float | None = Field(default=None, ge=0)
    distinct_nearby_nct_count: int = Field(ge=0)
    inclusive_radius_km: float = Field(ge=0)
    condition_filter: str | None = None
    total_site_count: int = Field(ge=0)
    resolved_site_count: int = Field(ge=0)
    unresolved_site_count: int = Field(ge=0)
    deduplicated_site_count: int = Field(ge=0)
    distance_limitation: Literal[
        "straight-line great-circle distance; not travel time or route distance"
    ] = "straight-line great-circle distance; not travel time or route distance"


class ScenarioConstructionReport(StrictModel):
    included_municipality_count: int = Field(ge=0)
    excluded_municipality_count: int = Field(ge=0)
    excluded_unresolved_point_count: int = Field(ge=0)
    excluded_null_population_count: int = Field(ge=0)
    excluded_missing_equity_indicator_count: int = Field(ge=0)
    aggregate_source_count: int = Field(ge=0)
    point_source: str
    equity_indicator: str
    equity_normalization_method: str
    equity_interpretation: str
    scenario_label: Literal["condition-independent; no live clinical-site records integrated"] = (
        "condition-independent; no live clinical-site records integrated"
    )
    event_cost_assumption: str
    assumptions: tuple[str, ...]


class DerivedMetricDefinition(StrictModel):
    name: str
    version: str
    direction: Literal["higher_is_more_access", "higher_is_less_access"]
    scale: str
    components: tuple[str, ...]
    assumptions: tuple[str, ...]
    missing_data_behavior: str
