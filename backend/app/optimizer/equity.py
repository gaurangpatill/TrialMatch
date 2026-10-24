"""Transparent normalization for geography-provided aggregate equity indicators."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

EQUITY_NORMALIZATION_METHOD = "min_max_ej_subset_indicator_v1"
EQUITY_NORMALIZATION_FORMULA = "E_i = (q_i - min(q)) / (max(q) - min(q))"
EQUITY_INTERPRETATION = (
    "E=0 is the lowest and E=1 the highest relative priority among communities "
    "for one documented aggregate EJ-subset indicator; E is not a patient attribute."
)


@dataclass(frozen=True)
class EquityNormalizationResult:
    """Normalized values and enough metadata to reproduce their interpretation."""

    priorities: dict[str, float | None]
    source_indicator: str
    observed_minimum: float | None
    observed_maximum: float | None
    method: str = EQUITY_NORMALIZATION_METHOD
    formula: str = EQUITY_NORMALIZATION_FORMULA
    interpretation: str = EQUITY_INTERPRETATION
    missing_value_behavior: str = "preserve null; caller must exclude or resolve explicitly"
    constant_value_behavior: str = "assign 0.5 to every observed value when max(q) equals min(q)"


def min_max_normalize_equity_priority(
    raw_values: Mapping[str, float | None], *, source_indicator: str
) -> EquityNormalizationResult:
    """Normalize one documented EJ-subset indicator without inventing a composite score.

    Missing values remain ``None``. If every observed value is equal, all observed
    communities receive neutral relative priority 0.5 because no ordering is present.
    The geography layer remains responsible for choosing and documenting ``q``.
    """

    indicator = source_indicator.strip()
    if not indicator:
        raise ValueError("source_indicator must identify the aggregate EJ-subset measure")

    observed: list[float] = []
    validated: dict[str, float | None] = {}
    for community_id, raw_value in raw_values.items():
        identifier = community_id.strip()
        if not identifier:
            raise ValueError("community IDs must not be blank")
        if identifier in validated:
            raise ValueError(f"duplicate normalized community ID: {identifier}")
        if raw_value is None:
            validated[identifier] = None
            continue
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError("raw equity indicator values must be finite or null")
        validated[identifier] = value
        observed.append(value)

    if not observed:
        return EquityNormalizationResult(
            priorities={key: None for key in sorted(validated)},
            source_indicator=indicator,
            observed_minimum=None,
            observed_maximum=None,
        )

    minimum = min(observed)
    maximum = max(observed)
    if maximum == minimum:
        priorities = {
            key: None if value is None else 0.5
            for key, value in sorted(validated.items())
        }
    else:
        scale = maximum - minimum
        priorities = {
            key: None if value is None else (value - minimum) / scale
            for key, value in sorted(validated.items())
        }

    return EquityNormalizationResult(
        priorities=priorities,
        source_indicator=indicator,
        observed_minimum=minimum,
        observed_maximum=maximum,
    )
