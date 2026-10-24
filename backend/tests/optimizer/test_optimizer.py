"""G6/G7 optimizer tests. Every coordinate here is an explicit synthetic fixture."""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from backend.app.optimizer import (
    CandidateLocation,
    DemandCommunity,
    OptimizationScenario,
    RawSolverResult,
    build_baselines,
    build_formulation,
    haversine_km,
    min_max_normalize_equity_priority,
    optimize,
)

SOURCE = "synthetic_test_fixture"
SOURCE_REF = "optimizer unit test only; not a real location"


def candidate(
    identifier: str,
    longitude: float,
    cost: float = 1.0,
    latitude: float = 0.0,
) -> CandidateLocation:
    return CandidateLocation(
        candidate_id=identifier,
        latitude=latitude,
        longitude=longitude,
        event_cost=cost,
        coordinate_source=SOURCE,
        coordinate_source_reference=SOURCE_REF,
    )


def community(
    identifier: str,
    longitude: float,
    population: int,
    equity: float = 0.5,
    latitude: float = 0.0,
) -> DemandCommunity:
    return DemandCommunity(
        community_id=identifier,
        latitude=latitude,
        longitude=longitude,
        ej_subset_population_proxy=population,
        equity_priority=equity,
        coordinate_source=SOURCE,
        coordinate_source_reference=SOURCE_REF,
    )


def scenario(**overrides: object) -> OptimizationScenario:
    values: dict[str, object] = {
        "candidates": (candidate("A", 0.0), candidate("B", 1.0)),
        "communities": (
            community("one", 0.0, 10, 0.2),
            community("two", 1.0, 7, 1.0),
        ),
        "budget": 1.0,
        "max_events": 1,
        "coverage_radius_km": 1.0,
        "equity_weight_lambda": 0.0,
    }
    values.update(overrides)
    return OptimizationScenario(**values)


def exhaustive_optimum(problem: OptimizationScenario) -> tuple[float, set[tuple[str, ...]]]:
    """Independent small-instance oracle using the built coverage matrix."""

    formulation = build_formulation(problem)
    required = set(problem.required_candidate_ids)
    best = -1.0
    selections: set[tuple[str, ...]] = set()
    for size in range(len(formulation.candidate_ids) + 1):
        for selected_ids in combinations(formulation.candidate_ids, size):
            if not required.issubset(selected_ids):
                continue
            indices = [formulation.candidate_ids.index(item) for item in selected_ids]
            if len(indices) > problem.max_events:
                continue
            if sum(formulation.candidate_costs[indices]) > problem.budget + 1e-8:
                continue
            covered = (
                np.flatnonzero(formulation.coverage_matrix[:, indices].any(axis=1))
                if indices
                else np.asarray([], dtype=int)
            )
            value = float(sum(formulation.community_weights[covered]))
            if value > best + 1e-8:
                best, selections = value, {selected_ids}
            elif abs(value - best) <= 1e-8:
                selections.add(selected_ids)
    return best, selections


class FakeBackend:
    name = "injected-test-solver"
    version = "test"

    def __init__(self, result: RawSolverResult | Exception):
        self.result = result

    def solve(self, formulation):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_known_optimum_matches_exhaustive_enumeration() -> None:
    problem = scenario(equity_weight_lambda=0.4)
    result = optimize(problem)
    expected, optimal_selections = exhaustive_optimum(problem)

    assert result.status == "optimal"
    assert result.modeled_outreach_coverage_objective == pytest.approx(expected)
    assert result.selected_municipality_ids in optimal_selections
    assert result.solver.name == "scipy.optimize.milp (HiGHS)"
    assert result.constraint_satisfaction.all_satisfied


def test_overlapping_catchments_count_each_community_once() -> None:
    problem = scenario(
        candidates=(candidate("A", 0.0), candidate("B", 0.01)),
        communities=(community("one", 0.005, 100),),
        budget=2,
        max_events=2,
        coverage_radius_km=2,
    )
    result = optimize(problem)

    assert result.status == "optimal"
    assert result.covered_community_ids == ("one",)
    assert result.modeled_ej_subset_population_proxy_covered == 100
    assert result.modeled_outreach_coverage_objective == 100


def test_budget_and_event_constraints_choose_best_feasible_plan() -> None:
    problem = scenario(
        candidates=(candidate("A", 0, 4), candidate("B", 1, 3), candidate("C", 2, 2)),
        communities=(
            community("a", 0, 8),
            community("b", 1, 7),
            community("c", 2, 4),
        ),
        budget=5,
        max_events=2,
    )
    result = optimize(problem)

    assert result.status == "optimal"
    assert result.selected_municipality_ids == ("B", "C")
    assert result.total_cost == 5
    assert result.total_events == 2
    assert result.modeled_outreach_coverage_objective == 11


@pytest.mark.parametrize(
    ("budget", "max_events", "expected"),
    [(0.0, 1, ("FREE",)), (10.0, 0, ())],
)
def test_zero_budget_and_zero_event_limit_are_valid(
    budget: float, max_events: int, expected: tuple[str, ...]
) -> None:
    problem = scenario(
        candidates=(candidate("FREE", 0, 0),),
        communities=(community("one", 0, 2),),
        budget=budget,
        max_events=max_events,
    )
    result = optimize(problem)
    assert result.status == "optimal"
    assert result.selected_municipality_ids == expected


@pytest.mark.parametrize(
    ("candidates", "communities"),
    [((), (community("one", 0, 5),)), ((), ())],
)
def test_empty_datasets_are_valid(candidates, communities) -> None:
    result = optimize(scenario(candidates=candidates, communities=communities))
    assert result.status == "optimal"
    assert result.selected_municipality_ids == ()
    assert result.covered_community_ids == ()
    assert result.modeled_outreach_coverage_objective == 0


def test_haversine_and_coverage_radius_are_inclusive_at_boundary() -> None:
    distance = haversine_km(0, 0, 0, 1)
    problem = scenario(
        candidates=(candidate("A", 0),),
        communities=(community("edge", 1, 1),),
        coverage_radius_km=distance,
    )
    formulation = build_formulation(problem)
    assert distance == pytest.approx(111.1950802335)
    assert formulation.coverage_matrix.tolist() == [[1]]


@pytest.mark.parametrize(
    ("coordinates", "message"),
    [((float("nan"), 0, 0, 0), "finite"), ((91, 0, 0, 0), "latitude"), ((0, 181, 0, 0), "longitude")],
)
def test_haversine_rejects_invalid_coordinates(coordinates, message) -> None:
    with pytest.raises(ValueError, match=message):
        haversine_km(*coordinates)


def test_lambda_zero_and_one_use_documented_weight_formula() -> None:
    base = scenario(
        candidates=(candidate("A", 0), candidate("B", 1)),
        communities=(community("a", 0, 100, 0.1), community("b", 1, 20, 1.0)),
    )
    population_result = optimize(base.model_copy(update={"equity_weight_lambda": 0.0}))
    equity_result = optimize(base.model_copy(update={"equity_weight_lambda": 1.0}))

    assert population_result.selected_municipality_ids == ("A",)
    assert population_result.modeled_outreach_coverage_objective == 100
    assert equity_result.selected_municipality_ids == ("B",)
    assert equity_result.modeled_outreach_coverage_objective == 20


def test_result_is_recomputed_from_inputs_not_solver_fun_or_y_values() -> None:
    problem = scenario(candidates=(candidate("A", 0, 2),), communities=(community("one", 0, 9, 0.5),), budget=2)
    # x=1 and exact y=1; RawSolverResult intentionally has no objective field.
    result = optimize(problem, FakeBackend(RawSolverResult(0, np.array([1.0, 1.0]), "ok", 0.0)))
    assert result.selected_municipality_ids == ("A",)
    assert result.covered_community_ids == ("one",)
    assert result.total_cost == 2
    assert result.modeled_ej_subset_population_proxy_covered == 9
    assert result.modeled_outreach_coverage_objective == 9


def test_deterministic_ordering_repeated_solves_and_baseline_ties() -> None:
    problem = scenario(
        candidates=(candidate("B", 0), candidate("A", 0)),
        communities=(community("one", 0, 10),),
    )
    selections = [optimize(problem).selected_municipality_ids for _ in range(5)]
    assert all(item == selections[0] for item in selections)
    formulation = build_formulation(problem)
    assert formulation.candidate_ids == ("A", "B")
    population, equity = build_baselines(problem, formulation)
    assert population.selected_municipality_ids == ("A",)
    assert equity.selected_municipality_ids == ("A",)


def test_baselines_use_marginal_unique_coverage_and_same_constraints() -> None:
    problem = scenario(
        candidates=(candidate("A", 0, 2), candidate("B", 0.01, 2), candidate("C", 1, 2)),
        communities=(community("shared", 0.005, 100, 0.1), community("other", 1, 60, 1.0)),
        budget=4,
        max_events=2,
        coverage_radius_km=2,
        equity_weight_lambda=0.5,
    )
    population, equity = build_baselines(problem, build_formulation(problem))

    assert population.selected_municipality_ids == ("A", "C")
    assert equity.selected_municipality_ids == ("A", "C")
    for baseline in (population, equity):
        assert baseline.covered_community_ids == ("other", "shared")
        assert baseline.modeled_ej_subset_population_proxy_covered == 160
        assert baseline.modeled_outreach_coverage_objective == 115
        assert baseline.constraint_satisfaction.all_satisfied


def test_population_and_equity_baselines_rank_different_marginal_gains() -> None:
    problem = scenario(
        candidates=(candidate("A", 0), candidate("B", 1)),
        communities=(community("a", 0, 100, 0.1), community("b", 1, 60, 1.0)),
        equity_weight_lambda=0.5,
    )
    population, equity = build_baselines(problem, build_formulation(problem))
    assert population.selected_municipality_ids == ("A",)
    assert equity.selected_municipality_ids == ("B",)
    assert population.modeled_outreach_coverage_objective == pytest.approx(55)
    assert equity.modeled_outreach_coverage_objective == pytest.approx(60)


def test_baselines_skip_unaffordable_and_no_gain_candidates() -> None:
    problem = scenario(
        candidates=(candidate("EMPTY", 5, 0), candidate("EXPENSIVE", 0, 20)),
        communities=(community("one", 0, 10),),
        budget=1,
        max_events=2,
    )
    for baseline in build_baselines(problem, build_formulation(problem)):
        assert baseline.selected_municipality_ids == ()


def test_required_candidates_can_make_real_scipy_model_infeasible() -> None:
    problem = scenario(
        candidates=(candidate("A", 0, 5),),
        communities=(community("one", 0, 10),),
        budget=4,
        max_events=1,
        required_candidate_ids=("A",),
    )
    result = optimize(problem)
    assert result.status == "infeasible"
    assert result.solver.native_status == 2
    assert result.selected_municipality_ids == ()
    assert not result.constraint_satisfaction.primal_validated
    assert not result.baselines[0].constraint_satisfaction.all_satisfied


@pytest.mark.parametrize(
    ("native_status", "primal", "expected"),
    [
        (0, np.array([1.0, 1.0]), "optimal"),
        (1, np.array([1.0, 1.0]), "feasible"),
        (2, None, "infeasible"),
        (3, None, "unbounded"),
        (4, None, "solver_error"),
        (0, np.array([0.5, 1.0]), "solver_error"),
        (1, None, "solver_error"),
    ],
)
def test_all_statuses_are_mapped_without_overclaiming(native_status, primal, expected) -> None:
    problem = scenario(candidates=(candidate("A", 0),), communities=(community("one", 0, 1),))
    result = optimize(problem, FakeBackend(RawSolverResult(native_status, primal, "injected")))
    assert result.status == expected
    if expected not in ("optimal", "feasible"):
        assert result.selected_municipality_ids == ()


def test_solver_exception_becomes_solver_error() -> None:
    result = optimize(scenario(), FakeBackend(RuntimeError("backend failed")))
    assert result.status == "solver_error"
    assert "RuntimeError: backend failed" in result.solver.message


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_cost", float("nan")),
        ("event_cost", float("inf")),
        ("event_cost", -1),
        ("latitude", None),
        ("latitude", 91),
        ("longitude", -181),
        ("coordinate_source", "unverified"),
    ],
)
def test_candidate_rejects_missing_nonfinite_range_and_source_errors(field, value) -> None:
    values = candidate("A", 0).model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        CandidateLocation(**values)


@pytest.mark.parametrize(
    "updates",
    [
        {"budget": float("nan")},
        {"budget": -1},
        {"max_events": -1},
        {"coverage_radius_km": float("inf")},
        {"coverage_radius_km": -1},
        {"equity_weight_lambda": -0.1},
        {"equity_weight_lambda": 1.1},
        {"candidates": (candidate("A", 0), candidate("A", 1))},
        {"communities": (community("x", 0, 1), community("x", 1, 1))},
        {"required_candidate_ids": ("UNKNOWN",)},
        {"required_candidate_ids": ("A", "A")},
    ],
)
def test_scenario_rejects_invalid_values_and_duplicate_or_unknown_ids(updates) -> None:
    values = scenario().model_dump()
    values.update(updates)
    with pytest.raises(ValidationError):
        OptimizationScenario(**values)


def test_scenario_rejects_finite_values_that_overflow_solver_arithmetic() -> None:
    with pytest.raises(ValidationError, match="converted and aggregated"):
        scenario(communities=(community("huge", 0, 10**400),))
    with pytest.raises(ValidationError, match="converted and aggregated"):
        scenario(
            candidates=(candidate("A", 0, 1e308), candidate("B", 1, 1e308)),
            required_candidate_ids=("A", "B"),
            budget=1e308,
            max_events=2,
        )


def test_demand_rejects_invalid_population_equity_and_nonfinite_values() -> None:
    base = community("x", 0, 1).model_dump()
    for field, value in (
        ("ej_subset_population_proxy", -1),
        ("equity_priority", -0.1),
        ("equity_priority", 1.1),
        ("equity_priority", float("nan")),
    ):
        with pytest.raises(ValidationError):
            DemandCommunity(**{**base, field: value})


def test_formulation_has_exact_or_constraints_for_zero_weight_coverage() -> None:
    problem = scenario(
        candidates=(candidate("A", 0),),
        communities=(community("zero", 0, 0, 0), community("uncovered", 5, 0, 0)),
        required_candidate_ids=("A",),
    )
    result = optimize(problem)
    assert result.status == "optimal"
    # Recomputed geometric coverage proves y semantics do not depend on objective weight.
    assert result.covered_community_ids == ("zero",)


@given(
    costs=st.lists(st.integers(min_value=0, max_value=10), min_size=0, max_size=5),
    budget=st.integers(min_value=0, max_value=20),
    max_events=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=30, deadline=None)
def test_property_successful_plans_respect_budget_and_event_limit(costs, budget, max_events) -> None:
    candidates = tuple(candidate(f"C{index}", index * 0.1, cost) for index, cost in enumerate(costs))
    communities = tuple(community(f"D{index}", index * 0.1, index + 1) for index in range(len(costs)))
    problem = scenario(
        candidates=candidates,
        communities=communities,
        budget=budget,
        max_events=max_events,
        coverage_radius_km=1,
    )
    result = optimize(problem)
    assert result.status == "optimal"
    assert result.total_cost <= budget + 1e-8
    assert result.total_events <= max_events
    assert result.constraint_satisfaction.all_satisfied


def test_equity_priority_min_max_normalization_is_reproducible() -> None:
    normalized = min_max_normalize_equity_priority(
        {"high": 30.0, "missing": None, "low": 10.0, "middle": 20.0},
        source_indicator="limited_english_population_weighted_ej_subset",
    )
    assert normalized.priorities == {
        "high": 1.0,
        "low": 0.0,
        "middle": 0.5,
        "missing": None,
    }
    assert normalized.observed_minimum == 10.0
    assert normalized.observed_maximum == 30.0
    assert "not a patient attribute" in normalized.interpretation
    assert "preserve null" in normalized.missing_value_behavior


def test_equity_priority_constant_indicator_has_neutral_relative_priority() -> None:
    normalized = min_max_normalize_equity_priority(
        {"B": 4.0, "A": 4.0}, source_indicator="documented_ej_subset_indicator"
    )
    assert normalized.priorities == {"A": 0.5, "B": 0.5}
    assert normalized.observed_minimum == normalized.observed_maximum == 4.0


@pytest.mark.parametrize(
    ("values", "indicator"),
    [({"A": float("nan")}, "valid"), ({"A": float("inf")}, "valid"), ({"A": 1.0}, " ")],
)
def test_equity_priority_normalization_rejects_unreproducible_inputs(values, indicator) -> None:
    with pytest.raises(ValueError):
        min_max_normalize_equity_priority(values, source_indicator=indicator)
