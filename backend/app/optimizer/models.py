"""Strict domain and result models for modeled outreach optimization."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CoordinateSource = Literal["synthetic_test_fixture", "verified_coordinate_source"]
SolverStatus = Literal["optimal", "feasible", "infeasible", "unbounded", "solver_error"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LocatedInput(StrictModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    coordinate_source: CoordinateSource
    coordinate_source_reference: str = Field(min_length=1)

    @field_validator("coordinate_source_reference")
    @classmethod
    def nonblank_reference(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("coordinate_source_reference must not be blank")
        return value


class CandidateLocation(LocatedInput):
    """A potential outreach-event municipality; coordinates are never inferred."""

    candidate_id: str = Field(min_length=1)
    event_cost: float = Field(ge=0, allow_inf_nan=False)
    cost_unit: Literal["usd_per_outreach_event"] = "usd_per_outreach_event"

    @field_validator("candidate_id")
    @classmethod
    def nonblank_candidate_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("candidate_id must not be blank")
        return value


class DemandCommunity(LocatedInput):
    """Aggregate community demand, never a patient-level observation."""

    community_id: str = Field(min_length=1)
    ej_subset_population_proxy: int = Field(ge=0)
    equity_priority: float = Field(ge=0, le=1, allow_inf_nan=False)
    population_scope: Literal[
        "EJ-flagged-block-group subset; not municipality-wide population"
    ] = "EJ-flagged-block-group subset; not municipality-wide population"

    @field_validator("community_id")
    @classmethod
    def nonblank_community_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("community_id must not be blank")
        return value


class OptimizationScenario(StrictModel):
    candidates: tuple[CandidateLocation, ...] = ()
    communities: tuple[DemandCommunity, ...] = ()
    budget: float = Field(ge=0, allow_inf_nan=False)
    max_events: int = Field(ge=0)
    coverage_radius_km: float = Field(ge=0, allow_inf_nan=False)
    equity_weight_lambda: float = Field(ge=0, le=1, allow_inf_nan=False)
    required_candidate_ids: tuple[str, ...] = ()
    objective_version: Literal["ej_subset_weighted_coverage_v1"] = (
        "ej_subset_weighted_coverage_v1"
    )

    @model_validator(mode="after")
    def validate_identifiers(self) -> "OptimizationScenario":
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate IDs must be unique")
        community_ids = [community.community_id for community in self.communities]
        if len(set(community_ids)) != len(community_ids):
            raise ValueError("community IDs must be unique")
        if len(set(self.required_candidate_ids)) != len(self.required_candidate_ids):
            raise ValueError("required candidate IDs must be unique")
        unknown = sorted(set(self.required_candidate_ids) - set(candidate_ids))
        if unknown:
            raise ValueError(f"unknown required candidate IDs: {', '.join(unknown)}")

        # Reject values that are individually finite but cannot form finite solver
        # coefficients or report aggregates (for example, a 400-digit population).
        try:
            costs = [float(candidate.event_cost) for candidate in self.candidates]
            populations = [
                float(community.ej_subset_population_proxy)
                for community in self.communities
            ]
            weights = [
                population
                * (
                    (1.0 - self.equity_weight_lambda)
                    + self.equity_weight_lambda * community.equity_priority
                )
                for population, community in zip(populations, self.communities)
            ]
            aggregates = (
                math.fsum(costs),
                math.fsum(populations),
                math.fsum(weights),
            )
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                "scenario numeric values must remain finite when converted and aggregated"
            ) from exc
        if not all(math.isfinite(value) for value in (*costs, *populations, *weights, *aggregates)):
            raise ValueError(
                "scenario numeric values must remain finite when converted and aggregated"
            )
        return self


class ConstraintSatisfaction(StrictModel):
    primal_validated: bool
    budget_satisfied: bool
    event_limit_satisfied: bool
    required_candidates_satisfied: bool
    exact_coverage_satisfied: bool
    all_satisfied: bool


class PlanMetrics(StrictModel):
    selected_municipality_ids: tuple[str, ...]
    covered_community_ids: tuple[str, ...]
    total_events: int = Field(ge=0)
    total_cost: float = Field(ge=0, allow_inf_nan=False)
    modeled_ej_subset_population_proxy_covered: int = Field(ge=0)
    modeled_outreach_coverage_objective: float = Field(ge=0, allow_inf_nan=False)
    constraint_satisfaction: ConstraintSatisfaction


class BaselineResult(PlanMetrics):
    strategy: Literal["population_first_greedy", "equity_first_greedy"]


class SolverDetails(StrictModel):
    name: str
    version: str
    native_status: int | None
    message: str
    mip_gap: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class OptimizationResult(PlanMetrics):
    status: SolverStatus
    solver: SolverDetails
    baselines: tuple[BaselineResult, ...]
    objective_version: Literal["ej_subset_weighted_coverage_v1"]
    equity_weight_lambda: float = Field(ge=0, le=1, allow_inf_nan=False)
    coverage_radius_km: float = Field(ge=0, allow_inf_nan=False)
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


def finite_float(value: object) -> bool:
    """Small utility used when validating untrusted solver outputs."""

    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
