"""Deterministic constrained greedy comparators."""

from __future__ import annotations

from typing import Literal

import numpy as np

from .formulation import MilpFormulation
from .models import BaselineResult, ConstraintSatisfaction, OptimizationScenario

Strategy = Literal["population_first_greedy", "equity_first_greedy"]
TOLERANCE = 1e-8


def _covered_indices(formulation: MilpFormulation, selected: set[int]) -> set[int]:
    if not selected or formulation.community_count == 0:
        return set()
    return set(np.flatnonzero(formulation.coverage_matrix[:, sorted(selected)].any(axis=1)))


def build_greedy_baseline(
    scenario: OptimizationScenario,
    formulation: MilpFormulation,
    strategy: Strategy,
) -> BaselineResult:
    """Select by marginal unique population or population*equity, then stable ID."""

    selected = set(formulation.required_candidate_indices)
    total_cost = float(sum(formulation.candidate_costs[index] for index in selected))
    covered = _covered_indices(formulation, selected)

    while len(selected) < scenario.max_events:
        ranked: list[tuple[float, str, int]] = []
        for index, candidate_id in enumerate(formulation.candidate_ids):
            if index in selected:
                continue
            cost = float(formulation.candidate_costs[index])
            if total_cost + cost > scenario.budget + TOLERANCE:
                continue
            newly_covered = set(np.flatnonzero(formulation.coverage_matrix[:, index])) - covered
            if strategy == "population_first_greedy":
                gain = float(sum(formulation.community_populations[list(newly_covered)]))
            else:
                gain = float(
                    sum(
                        formulation.community_populations[list(newly_covered)]
                        * formulation.community_equity_priorities[list(newly_covered)]
                    )
                )
            if gain > TOLERANCE:
                ranked.append((-gain, candidate_id, index))
        if not ranked:
            break
        _, _, chosen = min(ranked)
        selected.add(chosen)
        total_cost += float(formulation.candidate_costs[chosen])
        covered = _covered_indices(formulation, selected)

    selected_ids = tuple(formulation.candidate_ids[index] for index in sorted(selected))
    covered_ids = tuple(formulation.community_ids[index] for index in sorted(covered))
    population = int(sum(formulation.community_populations[list(covered)])) if covered else 0
    objective = float(sum(formulation.community_weights[list(covered)])) if covered else 0.0
    required_ok = set(formulation.required_candidate_indices).issubset(selected)
    budget_ok = total_cost <= scenario.budget + TOLERANCE
    event_ok = len(selected) <= scenario.max_events
    constraints = ConstraintSatisfaction(
        primal_validated=True,
        budget_satisfied=budget_ok,
        event_limit_satisfied=event_ok,
        required_candidates_satisfied=required_ok,
        exact_coverage_satisfied=True,
        all_satisfied=budget_ok and event_ok and required_ok,
    )
    return BaselineResult(
        strategy=strategy,
        selected_municipality_ids=selected_ids,
        covered_community_ids=covered_ids,
        total_events=len(selected_ids),
        total_cost=total_cost,
        modeled_ej_subset_population_proxy_covered=population,
        modeled_outreach_coverage_objective=objective,
        constraint_satisfaction=constraints,
    )


def build_baselines(
    scenario: OptimizationScenario, formulation: MilpFormulation
) -> tuple[BaselineResult, BaselineResult]:
    return (
        build_greedy_baseline(scenario, formulation, "population_first_greedy"),
        build_greedy_baseline(scenario, formulation, "equity_first_greedy"),
    )
