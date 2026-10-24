"""Construct optimizer scenarios from real EJ aggregates and verified points."""

from __future__ import annotations

from collections.abc import Iterable

from backend.app.optimizer import (
    CandidateLocation, DemandCommunity, OptimizationScenario,
    min_max_normalize_equity_priority,
)

from .models import MunicipalityEJSubsetAggregate, MunicipalityRepresentativePoint, ScenarioConstructionReport

EQUITY_INDICATOR = "limited_english_population_weighted_ej_subset"


def build_real_ej_scenario(
    aggregates: Iterable[MunicipalityEJSubsetAggregate],
    points: Iterable[MunicipalityRepresentativePoint], *, budget: float,
    max_events: int, coverage_radius_km: float, equity_weight_lambda: float,
    event_cost: float = 1.0, point_source: str,
) -> tuple[OptimizationScenario, ScenarioConstructionReport]:
    aggregate_list = tuple(aggregates)
    point_by_name = {point.municipality: point for point in points}
    unresolved = null_population = missing_equity = 0
    eligible: list[tuple[MunicipalityEJSubsetAggregate, MunicipalityRepresentativePoint]] = []
    for aggregate in sorted(aggregate_list, key=lambda x: (x.municipality.casefold(), x.municipality)):
        point = point_by_name.get(aggregate.municipality)
        if point is None or point.resolution_status != "resolved":
            unresolved += 1
            continue
        if aggregate.total_population_ej_subset is None:
            null_population += 1
            continue
        if aggregate.limited_english_population_weighted_ej_subset is None:
            missing_equity += 1
            continue
        eligible.append((aggregate, point))
    normalization = min_max_normalize_equity_priority(
        {aggregate.municipality: aggregate.limited_english_population_weighted_ej_subset for aggregate, _ in eligible},
        source_indicator=EQUITY_INDICATOR,
    )
    candidates = []
    communities = []
    reference = f"{point_source}; municipality EJ representative analytical point"
    for aggregate, point in eligible:
        assert point.latitude is not None and point.longitude is not None
        priority = normalization.priorities[aggregate.municipality]
        assert priority is not None
        candidates.append(CandidateLocation(
            candidate_id=aggregate.municipality, latitude=point.latitude, longitude=point.longitude,
            coordinate_source="verified_coordinate_source", coordinate_source_reference=reference,
            event_cost=event_cost, cost_unit="abstract_equal_event_units",
        ))
        communities.append(DemandCommunity(
            community_id=aggregate.municipality, latitude=point.latitude, longitude=point.longitude,
            coordinate_source="verified_coordinate_source", coordinate_source_reference=reference,
            ej_subset_population_proxy=aggregate.total_population_ej_subset,
            equity_priority=priority,
        ))
    scenario = OptimizationScenario(
        candidates=tuple(candidates), communities=tuple(communities), budget=budget,
        max_events=max_events, coverage_radius_km=coverage_radius_km,
        equity_weight_lambda=equity_weight_lambda,
        cost_unit="abstract_equal_event_units",
    )
    excluded = unresolved + null_population + missing_equity
    report = ScenarioConstructionReport(
        included_municipality_count=len(eligible), excluded_municipality_count=excluded,
        excluded_unresolved_point_count=unresolved, excluded_null_population_count=null_population,
        excluded_missing_equity_indicator_count=missing_equity,
        aggregate_source_count=len(aggregate_list), point_source=point_source,
        equity_indicator=EQUITY_INDICATOR, equity_normalization_method=normalization.method,
        equity_interpretation=normalization.interpretation,
        event_cost_assumption="Numeric 1 represents equal abstract event units; it is not an observed monetary cost.",
        assumptions=("E is relative only within included municipalities.", "Inputs are aggregate EJ-subset data, never individual data.", "Scenario is condition-independent because no live clinical-site export is integrated."),
    )
    return scenario, report
