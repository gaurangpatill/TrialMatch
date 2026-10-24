"""Pure distance, coverage, and MILP array construction."""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

import numpy as np

from .models import OptimizationScenario

EARTH_RADIUS_KM = 6371.0088
COVERAGE_BOUNDARY_TOLERANCE_KM = 1e-9


@dataclass(frozen=True)
class MilpFormulation:
    candidate_ids: tuple[str, ...]
    community_ids: tuple[str, ...]
    candidate_costs: np.ndarray
    community_populations: np.ndarray
    community_equity_priorities: np.ndarray
    community_weights: np.ndarray
    coverage_matrix: np.ndarray
    objective: np.ndarray
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    integrality: np.ndarray
    constraint_matrix: np.ndarray
    constraint_lower_bounds: np.ndarray
    constraint_upper_bounds: np.ndarray
    required_candidate_indices: tuple[int, ...]

    @property
    def candidate_count(self) -> int:
        return len(self.candidate_ids)

    @property
    def community_count(self) -> int:
        return len(self.community_ids)

    @property
    def variable_count(self) -> int:
        return self.candidate_count + self.community_count


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance in kilometers for validated finite coordinates."""

    coordinates = (latitude_a, longitude_a, latitude_b, longitude_b)
    if not all(np.isfinite(value) for value in coordinates):
        raise ValueError("coordinates must be finite")
    if not -90 <= latitude_a <= 90 or not -90 <= latitude_b <= 90:
        raise ValueError("latitude must be in [-90, 90]")
    if not -180 <= longitude_a <= 180 or not -180 <= longitude_b <= 180:
        raise ValueError("longitude must be in [-180, 180]")

    lat_a, lat_b = radians(latitude_a), radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = radians(longitude_b - longitude_a)
    haversine = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, max(0.0, haversine))))


def build_formulation(scenario: OptimizationScenario) -> MilpFormulation:
    """Build deterministic x-then-y binary maximum-coverage arrays.

    ``x[j]`` selects a candidate and ``y[i]`` is the exact logical OR of selected
    candidates covering community ``i``. SciPy minimizes, so y coefficients are
    negative weighted population proxies.
    """

    candidates = tuple(sorted(scenario.candidates, key=lambda item: item.candidate_id))
    communities = tuple(sorted(scenario.communities, key=lambda item: item.community_id))
    candidate_ids = tuple(item.candidate_id for item in candidates)
    community_ids = tuple(item.community_id for item in communities)
    costs = np.asarray([item.event_cost for item in candidates], dtype=float)
    populations = np.asarray(
        [item.ej_subset_population_proxy for item in communities], dtype=float
    )
    equity = np.asarray([item.equity_priority for item in communities], dtype=float)
    weights = populations * (
        (1.0 - scenario.equity_weight_lambda)
        + scenario.equity_weight_lambda * equity
    )

    coverage = np.zeros((len(communities), len(candidates)), dtype=np.int8)
    for community_index, community in enumerate(communities):
        for candidate_index, candidate in enumerate(candidates):
            distance = haversine_km(
                community.latitude,
                community.longitude,
                candidate.latitude,
                candidate.longitude,
            )
            if distance <= scenario.coverage_radius_km + COVERAGE_BOUNDARY_TOLERANCE_KM:
                coverage[community_index, candidate_index] = 1

    candidate_count = len(candidates)
    community_count = len(communities)
    variable_count = candidate_count + community_count
    objective = np.concatenate((np.zeros(candidate_count), -weights))
    lower_bounds = np.zeros(variable_count)
    upper_bounds = np.ones(variable_count)
    integrality = np.ones(variable_count, dtype=np.int8)

    rows: list[np.ndarray] = []
    lower: list[float] = []
    upper: list[float] = []

    budget_row = np.zeros(variable_count)
    budget_row[:candidate_count] = costs
    rows.append(budget_row)
    lower.append(-np.inf)
    upper.append(scenario.budget)

    event_row = np.zeros(variable_count)
    event_row[:candidate_count] = 1.0
    rows.append(event_row)
    lower.append(-np.inf)
    upper.append(float(scenario.max_events))

    # y_i <= sum_j(a_ij*x_j), including y_i <= 0 for uncovered rows.
    for community_index in range(community_count):
        row = np.zeros(variable_count)
        row[:candidate_count] = -coverage[community_index]
        row[candidate_count + community_index] = 1.0
        rows.append(row)
        lower.append(-np.inf)
        upper.append(0.0)

        # Every covered selected candidate implies y_i >= x_j.
        for candidate_index in np.flatnonzero(coverage[community_index]):
            implication = np.zeros(variable_count)
            implication[candidate_index] = 1.0
            implication[candidate_count + community_index] = -1.0
            rows.append(implication)
            lower.append(-np.inf)
            upper.append(0.0)

    index_by_id = {candidate_id: index for index, candidate_id in enumerate(candidate_ids)}
    required_indices = tuple(
        sorted(index_by_id[candidate_id] for candidate_id in scenario.required_candidate_ids)
    )
    for candidate_index in required_indices:
        required_row = np.zeros(variable_count)
        required_row[candidate_index] = 1.0
        rows.append(required_row)
        lower.append(1.0)
        upper.append(1.0)

    matrix = np.vstack(rows) if rows else np.empty((0, variable_count))
    return MilpFormulation(
        candidate_ids=candidate_ids,
        community_ids=community_ids,
        candidate_costs=costs,
        community_populations=populations,
        community_equity_priorities=equity,
        community_weights=weights,
        coverage_matrix=coverage,
        objective=objective,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        integrality=integrality,
        constraint_matrix=matrix,
        constraint_lower_bounds=np.asarray(lower),
        constraint_upper_bounds=np.asarray(upper),
        required_candidate_indices=required_indices,
    )
