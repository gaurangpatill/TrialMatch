"""SciPy MILP invocation, honest status mapping, and source-based recomputation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp

from .baseline import build_baselines
from .formulation import MilpFormulation, build_formulation
from .models import (
    ConstraintSatisfaction,
    OptimizationResult,
    OptimizationScenario,
    SolverDetails,
    finite_float,
)

PRIMAL_TOLERANCE = 1e-6
ASSUMPTIONS = (
    "Coverage is modeled as inclusive great-circle distance within the configured radius.",
    "Population is an EJ-flagged block-group subset proxy, not municipality-wide population.",
    "Equity priority E is normalized from one documented aggregate EJ-subset indicator as "
    "(q_i - min(q)) / (max(q) - min(q)); 0 is lowest and 1 highest relative priority, "
    "missing values remain null, and a constant observed indicator maps to neutral 0.5.",
    "The objective weight is w_i = P_i * ((1 - lambda) + lambda * E_i).",
    "Each covered community contributes at most once, regardless of catchment overlap.",
)
LIMITATIONS = (
    "Modeled outreach coverage is not an enrollment prediction or causal outcome.",
    "Coordinates must come from an explicit source; this engine never geocodes or invents them.",
    "No real statewide coordinate dataset is integrated by this optimizer module.",
)


@dataclass(frozen=True)
class RawSolverResult:
    status: int
    x: np.ndarray | None
    message: str
    mip_gap: float | None = None


class SolverBackend(Protocol):
    name: str
    version: str

    def solve(self, formulation: MilpFormulation) -> RawSolverResult: ...


class ScipyMilpBackend:
    name = "scipy.optimize.milp (HiGHS)"
    version = scipy.__version__

    def solve(self, formulation: MilpFormulation) -> RawSolverResult:
        result = milp(
            c=formulation.objective,
            integrality=formulation.integrality,
            bounds=Bounds(formulation.lower_bounds, formulation.upper_bounds),
            constraints=LinearConstraint(
                formulation.constraint_matrix,
                formulation.constraint_lower_bounds,
                formulation.constraint_upper_bounds,
            ),
            options={"disp": False},
        )
        return RawSolverResult(
            status=int(result.status),
            x=None if result.x is None else np.asarray(result.x, dtype=float),
            message=str(result.message),
            mip_gap=(
                float(result.mip_gap)
                if getattr(result, "mip_gap", None) is not None
                and finite_float(result.mip_gap)
                and float(result.mip_gap) >= 0
                else None
            ),
        )


def _validated_binary_primal(
    raw_x: np.ndarray | None, formulation: MilpFormulation
) -> np.ndarray | None:
    if raw_x is None:
        return None
    values = np.asarray(raw_x, dtype=float)
    if values.shape != (formulation.variable_count,) or not np.all(np.isfinite(values)):
        return None
    rounded = np.rint(values)
    if np.any(np.abs(values - rounded) > PRIMAL_TOLERANCE):
        return None
    if np.any(rounded < 0) or np.any(rounded > 1):
        return None
    activity = formulation.constraint_matrix @ rounded
    lower_ok = np.all(
        np.isneginf(formulation.constraint_lower_bounds)
        | (activity >= formulation.constraint_lower_bounds - PRIMAL_TOLERANCE)
    )
    upper_ok = np.all(
        np.isposinf(formulation.constraint_upper_bounds)
        | (activity <= formulation.constraint_upper_bounds + PRIMAL_TOLERANCE)
    )
    return rounded.astype(np.int8) if lower_ok and upper_ok else None


def _metrics_from_selection(
    scenario: OptimizationScenario,
    formulation: MilpFormulation,
    selected: set[int],
    *,
    primal_validated: bool,
) -> dict[str, object]:
    if selected and formulation.community_count:
        covered = set(
            np.flatnonzero(formulation.coverage_matrix[:, sorted(selected)].any(axis=1))
        )
    else:
        covered = set()
    selected_ids = tuple(formulation.candidate_ids[index] for index in sorted(selected))
    covered_ids = tuple(formulation.community_ids[index] for index in sorted(covered))
    cost = float(sum(formulation.candidate_costs[index] for index in selected))
    population = int(sum(formulation.community_populations[list(covered)])) if covered else 0
    objective = float(sum(formulation.community_weights[list(covered)])) if covered else 0.0
    budget_ok = cost <= scenario.budget + PRIMAL_TOLERANCE
    event_ok = len(selected) <= scenario.max_events
    required_ok = set(formulation.required_candidate_indices).issubset(selected)
    constraints = ConstraintSatisfaction(
        primal_validated=primal_validated,
        budget_satisfied=budget_ok,
        event_limit_satisfied=event_ok,
        required_candidates_satisfied=required_ok,
        exact_coverage_satisfied=primal_validated,
        all_satisfied=primal_validated and budget_ok and event_ok and required_ok,
    )
    return {
        "selected_municipality_ids": selected_ids,
        "covered_community_ids": covered_ids,
        "total_events": len(selected_ids),
        "total_cost": cost,
        "cost_unit": scenario.cost_unit,
        "modeled_ej_subset_population_proxy_covered": population,
        "modeled_outreach_coverage_objective": objective,
        "constraint_satisfaction": constraints,
    }


def optimize(
    scenario: OptimizationScenario,
    backend: SolverBackend | None = None,
) -> OptimizationResult:
    formulation = build_formulation(scenario)
    solver = backend or ScipyMilpBackend()
    baselines = build_baselines(scenario, formulation)

    try:
        if formulation.variable_count == 0:
            raw = RawSolverResult(0, np.empty(0), "Empty model is trivially optimal", 0.0)
        else:
            raw = solver.solve(formulation)
    except Exception as exc:  # solver boundary: failures become explicit results
        raw = RawSolverResult(4, None, f"Solver exception: {type(exc).__name__}: {exc}")

    primal = _validated_binary_primal(raw.x, formulation)
    status_by_native = {2: "infeasible", 3: "unbounded"}
    if raw.status == 0 and primal is not None:
        status = "optimal"
    elif raw.status == 1 and primal is not None:
        status = "feasible"
    elif raw.status in status_by_native:
        status = status_by_native[raw.status]
        primal = None
    else:
        status = "solver_error"
        primal = None

    selected = (
        set(np.flatnonzero(primal[: formulation.candidate_count]))
        if primal is not None
        else set()
    )
    metrics = _metrics_from_selection(
        scenario, formulation, selected, primal_validated=primal is not None
    )
    message = raw.message
    if raw.status in (0, 1) and primal is None:
        message = f"{message}; solver did not provide a valid feasible integral primal"
    details = SolverDetails(
        name=solver.name,
        version=solver.version,
        native_status=raw.status,
        message=message,
        mip_gap=(
            raw.mip_gap
            if raw.mip_gap is not None
            and finite_float(raw.mip_gap)
            and raw.mip_gap >= 0
            else None
        ),
    )
    return OptimizationResult(
        status=status,
        solver=details,
        baselines=baselines,
        objective_version=scenario.objective_version,
        equity_weight_lambda=scenario.equity_weight_lambda,
        coverage_radius_km=scenario.coverage_radius_km,
        assumptions=ASSUMPTIONS + (
            (
                "Candidate costs are additive assumed USD amounts per outreach event."
                if scenario.cost_unit == "usd_per_outreach_event"
                else "Candidate costs are equal abstract event units, not observed monetary costs."
            ),
        ),
        limitations=LIMITATIONS,
        **metrics,
    )
