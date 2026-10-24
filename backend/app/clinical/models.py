"""Validated source, domain, API, and eligibility models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """Base model for structures controlled by TrialMatch."""

    model_config = ConfigDict(extra="forbid")


class SourcePage(BaseModel):
    """Minimal validation for a ClinicalTrials.gov page envelope."""

    model_config = ConfigDict(extra="ignore")

    studies: list[dict[str, Any]]
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class SourceIdentification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nct_id: str = Field(alias="nctId", pattern=r"^NCT\d{8}$")
    brief_title: str | None = Field(default=None, alias="briefTitle")


class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    overall_status: str | None = Field(default=None, alias="overallStatus")


class SourceConditions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conditions: list[str] = Field(default_factory=list)


class SourceDesign(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phases: list[str] = Field(default_factory=list)


class SourceEligibility(BaseModel):
    model_config = ConfigDict(extra="ignore")

    eligibility_criteria: str | None = Field(default=None, alias="eligibilityCriteria")
    minimum_age: str | None = Field(default=None, alias="minimumAge")
    maximum_age: str | None = Field(default=None, alias="maximumAge")
    sex: str | None = None


class SourceGeoPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latitude: float | None = Field(default=None, alias="lat")
    longitude: float | None = Field(default=None, alias="lon")


class SourceContact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    role: str | None = None
    phone: str | None = None
    email: str | None = None


class SourceLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    facility: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = Field(default=None, alias="zip")
    country: str | None = None
    geo_point: SourceGeoPoint | None = Field(default=None, alias="geoPoint")
    contacts: list[SourceContact] = Field(default_factory=list)


class SourceContactsLocations(BaseModel):
    model_config = ConfigDict(extra="ignore")

    central_contacts: list[SourceContact] = Field(default_factory=list, alias="centralContacts")
    locations: list[SourceLocation] = Field(default_factory=list)


class SourceProtocol(BaseModel):
    model_config = ConfigDict(extra="ignore")

    identification: SourceIdentification = Field(alias="identificationModule")
    status: SourceStatus = Field(default_factory=SourceStatus, alias="statusModule")
    conditions: SourceConditions = Field(default_factory=SourceConditions, alias="conditionsModule")
    design: SourceDesign = Field(default_factory=SourceDesign, alias="designModule")
    eligibility: SourceEligibility = Field(default_factory=SourceEligibility, alias="eligibilityModule")
    contacts_locations: SourceContactsLocations = Field(
        default_factory=SourceContactsLocations, alias="contactsLocationsModule"
    )


class SourceStudy(BaseModel):
    """Supported source fields; unknown official fields are retained separately as raw JSON."""

    model_config = ConfigDict(extra="ignore")

    protocol: SourceProtocol = Field(alias="protocolSection")


class StudyLocation(StrictModel):
    facility: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class StudyContact(StrictModel):
    name: str | None = None
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    facility: str | None = None


class Study(StrictModel):
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    title: str = Field(min_length=1)
    overall_status: str = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)
    phases: list[str] = Field(default_factory=list)
    eligibility_criteria: str | None = None
    minimum_age: str | None = None
    maximum_age: str | None = None
    sex: str | None = None
    locations: list[StudyLocation] = Field(default_factory=list)
    contacts: list[StudyContact] = Field(default_factory=list)
    source_url: str
    retrieved_at: datetime
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_source: dict[str, Any]


class IngestionStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class IngestionReport(StrictModel):
    source_url: str
    started_at: datetime
    completed_at: datetime
    status: IngestionStatus
    page_count: int = Field(ge=0)
    raw_record_count: int = Field(ge=0)
    accepted_record_count: int = Field(ge=0)
    duplicate_identifier_count: int = Field(ge=0)
    missing_value_counts: dict[str, int]
    excluded_records: list[dict[str, str]]
    errors: list[str]
    detail_requested_count: int = Field(ge=0)
    detail_retrieved_count: int = Field(ge=0)


class CriterionClassification(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class CriterionStatus(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


class ScreeningStatus(str, Enum):
    POTENTIAL_MATCH = "potential_match"
    KNOWN_MISMATCH = "known_mismatch"
    UNRESOLVED = "unresolved"


class CriterionAttribute(str, Enum):
    AGE_YEARS = "age_years"
    SEX = "sex"
    CONDITION = "condition"
    MEDICATION = "medication"
    PROCEDURE = "procedure"
    LABORATORY_VALUE = "laboratory_value"
    UNSUPPORTED = "unsupported"


class CriterionOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    PRESENT = "present"
    ABSENT = "absent"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    BETWEEN = "between"
    WITHIN_DAYS = "within_days"
    ALL = "all"
    ANY = "any"
    UNSUPPORTED = "unsupported"


Scalar = StrictStr | StrictInt | StrictFloat | StrictBool


class Predicate(StrictModel):
    attribute: CriterionAttribute
    operator: CriterionOperator
    target: str | None = None
    value: Scalar | None = None
    lower: float | None = None
    upper: float | None = None
    include_lower: bool = True
    include_upper: bool = True
    unit: str | None = None
    temporal_window_days: int | None = Field(default=None, gt=0)
    children: list[Predicate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_operator_shape(self) -> Predicate:
        if self.operator in {CriterionOperator.ALL, CriterionOperator.ANY}:
            if len(self.children) < 2:
                raise ValueError("compound predicates require at least two children")
        elif self.children:
            raise ValueError("only compound predicates may contain children")

        if self.operator == CriterionOperator.BETWEEN:
            if self.lower is None or self.upper is None:
                raise ValueError("between requires lower and upper")
            if self.lower > self.upper:
                raise ValueError("between lower cannot exceed upper")
        if self.operator == CriterionOperator.WITHIN_DAYS and self.temporal_window_days is None:
            raise ValueError("within_days requires temporal_window_days")
        if self.attribute in {
            CriterionAttribute.CONDITION,
            CriterionAttribute.MEDICATION,
            CriterionAttribute.PROCEDURE,
            CriterionAttribute.LABORATORY_VALUE,
        } and not self.target:
            raise ValueError(f"{self.attribute.value} predicates require target")
        if self.operator in {
            CriterionOperator.EQUALS,
            CriterionOperator.NOT_EQUALS,
            CriterionOperator.GREATER_THAN,
            CriterionOperator.GREATER_THAN_OR_EQUAL,
            CriterionOperator.LESS_THAN,
            CriterionOperator.LESS_THAN_OR_EQUAL,
        } and self.value is None:
            raise ValueError(f"{self.operator.value} requires value")
        return self


class StructuredCriterion(StrictModel):
    criterion_id: str = Field(min_length=1)
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    classification: CriterionClassification
    original_text: str = Field(min_length=1)
    predicate: Predicate
    source_url: str
    extraction_uncertainty: str | None = None
    extraction_method: Literal["source_structured", "llm", "test_fixture"]
    schema_version: str = "1.0"
    provider: str | None = None
    model: str | None = None
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime


class ExtractionCandidate(StrictModel):
    classification: CriterionClassification
    original_text: str = Field(min_length=1)
    predicate: Predicate
    uncertainty: str | None = None


class ExtractionPayload(StrictModel):
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    criteria: list[ExtractionCandidate]


class SyntheticPatient(StrictModel):
    profile_id: str = Field(min_length=1, max_length=100)
    synthetic: Literal[True]
    age_years: float | None = Field(default=None, ge=0, le=125)
    sex: str | None = None
    conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    laboratory_values: dict[str, float] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conditions", "medications", "procedures")
    @classmethod
    def unique_normalized_facts(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("facts cannot be blank")
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result


class PatientRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=100)
    synthetic: bool
    age_years: float | None = Field(default=None, ge=0, le=125)
    sex: str | None = None
    conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    laboratory_values: dict[str, float] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class MatchRequest(StrictModel):
    patient: PatientRequest
    trial_ids: list[str] | None = Field(default=None, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("trial_ids")
    @classmethod
    def validate_trial_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if len(values) != len(set(values)):
            raise ValueError("trial_ids must be unique")
        for value in values:
            if not value.startswith("NCT") or len(value) != 11 or not value[3:].isdigit():
                raise ValueError(f"invalid NCT identifier: {value}")
        return values


class StudySummary(StrictModel):
    nct_id: str
    title: str
    overall_status: str
    conditions: list[str]
    phases: list[str]
    minimum_age: str | None
    maximum_age: str | None
    sex: str | None
    locations: list[StudyLocation]
    source_url: str
    retrieved_at: datetime


class Pagination(StrictModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class DataFreshness(StrictModel):
    retrieved_at: datetime | None
    source: Literal["ClinicalTrials.gov"] = "ClinicalTrials.gov"


class TrialSearchResponse(StrictModel):
    items: list[StudySummary]
    pagination: Pagination
    data_freshness: DataFreshness


class CriterionEvaluation(StrictModel):
    criterion_id: str
    classification: CriterionClassification
    status: CriterionStatus
    original_text: str
    explanation: str
    source_url: str
    extraction_uncertainty: str | None


class TrialMatchResult(StrictModel):
    nct_id: str
    title: str
    screening_status: ScreeningStatus
    criteria: list[CriterionEvaluation]
    known_mismatches: list[str]
    unresolved_requirements: list[str]
    missing_questions: list[str]
    source_url: str


class MatchResponse(StrictModel):
    profile_id: str
    results: list[TrialMatchResult]
    disclaimer: Literal["Preliminary screening only. Study staff must confirm eligibility."] = (
        "Preliminary screening only. Study staff must confirm eligibility."
    )
    generated_at: datetime


class ErrorDetail(StrictModel):
    field: str | None = None
    reason: str


class ErrorBody(StrictModel):
    code: str
    message: str
    details: list[ErrorDetail]
    retryable: bool
    request_id: str


class ErrorResponse(StrictModel):
    error: ErrorBody
