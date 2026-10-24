"""Deterministic budgeted maximum-coverage optimization boundary."""

from .baseline import build_baselines, build_greedy_baseline
from .equity import (
    EQUITY_INTERPRETATION,
    EQUITY_NORMALIZATION_FORMULA,
    EQUITY_NORMALIZATION_METHOD,
    EquityNormalizationResult,
    min_max_normalize_equity_priority,
)
from .formulation import MilpFormulation, build_formulation, haversine_km
from .models import (
    BaselineResult,
    CandidateLocation,
    DemandCommunity,
    OptimizationResult,
    OptimizationScenario,
)
from .solver import RawSolverResult, ScipyMilpBackend, SolverBackend, optimize

__all__ = [
    "EQUITY_INTERPRETATION",
    "EQUITY_NORMALIZATION_FORMULA",
    "EQUITY_NORMALIZATION_METHOD",
    "EquityNormalizationResult",
    "BaselineResult",
    "CandidateLocation",
    "DemandCommunity",
    "MilpFormulation",
    "OptimizationResult",
    "OptimizationScenario",
    "RawSolverResult",
    "ScipyMilpBackend",
    "SolverBackend",
    "build_baselines",
    "build_formulation",
    "build_greedy_baseline",
    "haversine_km",
    "min_max_normalize_equity_priority",
    "optimize",
]
