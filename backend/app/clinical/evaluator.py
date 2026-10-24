"""Pure deterministic three-state eligibility criterion evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import (
    CriterionAttribute,
    CriterionClassification,
    CriterionEvaluation,
    CriterionOperator,
    CriterionStatus,
    Predicate,
    StructuredCriterion,
    SyntheticPatient,
)


@dataclass(frozen=True)
class PredicateResult:
    value: bool | None
    reason: str


def evaluate_criterion(
    criterion: StructuredCriterion, patient: SyntheticPatient
) -> CriterionEvaluation:
    predicate_result = evaluate_predicate(criterion.predicate, patient)
    if predicate_result.value is None:
        status = CriterionStatus.UNKNOWN
        explanation = (
            "Insufficient synthetic profile information to evaluate this source criterion: "
            f"{predicate_result.reason}"
        )
    else:
        predicate_applies = predicate_result.value
        if criterion.classification == CriterionClassification.INCLUSION:
            status = CriterionStatus.MET if predicate_applies else CriterionStatus.NOT_MET
            direction = "satisfies" if predicate_applies else "does not satisfy"
            explanation = (
                f"The available synthetic profile fact {direction} this inclusion predicate: "
                f"{predicate_result.reason}"
            )
        else:
            status = CriterionStatus.NOT_MET if predicate_applies else CriterionStatus.MET
            direction = "satisfies" if predicate_applies else "explicitly does not satisfy"
            explanation = (
                f"The available synthetic profile fact {direction} this exclusion predicate: "
                f"{predicate_result.reason}"
            )
    return CriterionEvaluation(
        criterion_id=criterion.criterion_id,
        classification=criterion.classification,
        status=status,
        original_text=criterion.original_text,
        explanation=explanation,
        source_url=criterion.source_url,
        extraction_uncertainty=criterion.extraction_uncertainty,
    )


def evaluate_predicate(predicate: Predicate, patient: SyntheticPatient) -> PredicateResult:
    if predicate.operator in {CriterionOperator.ALL, CriterionOperator.ANY}:
        return _evaluate_compound(predicate, patient)
    if predicate.attribute == CriterionAttribute.UNSUPPORTED or predicate.operator == CriterionOperator.UNSUPPORTED:
        return PredicateResult(None, "the criterion is outside the supported deterministic vocabulary")
    if predicate.attribute == CriterionAttribute.AGE_YEARS:
        return _evaluate_numeric(patient.age_years, predicate, "age in years")
    if predicate.attribute == CriterionAttribute.SEX:
        if patient.sex is None:
            return PredicateResult(None, "sex is not provided")
        return _evaluate_comparable(patient.sex.casefold(), predicate, "sex")
    if predicate.attribute in {
        CriterionAttribute.CONDITION,
        CriterionAttribute.MEDICATION,
        CriterionAttribute.PROCEDURE,
    }:
        return _evaluate_fact(predicate, patient)
    if predicate.attribute == CriterionAttribute.LABORATORY_VALUE:
        assert predicate.target is not None
        # The shared API currently carries bare numbers, not unit-bearing lab facts.
        # A unit-sensitive protocol comparison cannot safely produce a definitive state.
        return PredicateResult(
            None,
            f"laboratory value {predicate.target} lacks a validated patient unit compatible with {predicate.unit}",
        )
    return PredicateResult(None, "the criterion attribute is unsupported")


def _evaluate_compound(predicate: Predicate, patient: SyntheticPatient) -> PredicateResult:
    results = [evaluate_predicate(child, patient) for child in predicate.children]
    values = [result.value for result in results]
    reasons = "; ".join(result.reason for result in results)
    if predicate.operator == CriterionOperator.ALL:
        if False in values:
            return PredicateResult(False, f"at least one required predicate is false ({reasons})")
        if all(value is True for value in values):
            return PredicateResult(True, f"all required predicates are true ({reasons})")
        return PredicateResult(None, f"at least one required predicate is unresolved ({reasons})")
    if True in values:
        return PredicateResult(True, f"at least one alternative predicate is true ({reasons})")
    if all(value is False for value in values):
        return PredicateResult(False, f"all alternative predicates are false ({reasons})")
    return PredicateResult(None, f"no alternative is true and at least one is unresolved ({reasons})")


def _evaluate_fact(predicate: Predicate, patient: SyntheticPatient) -> PredicateResult:
    assert predicate.target is not None
    attribute_name = predicate.attribute.value
    positive_values = {
        value.casefold()
        for value in getattr(patient, f"{attribute_name}s")
    }
    absent_values = {
        value.casefold() for value in getattr(patient, f"absent_{attribute_name}s")
    }
    target = predicate.target.casefold()

    if predicate.operator == CriterionOperator.WITHIN_DAYS:
        if target in absent_values:
            return PredicateResult(False, f"{predicate.target} is explicitly absent")
        if target not in positive_values:
            return PredicateResult(None, f"presence of {predicate.target} is not explicitly known")
        mapping_name = f"{attribute_name}_days_ago"
        raw_mapping = getattr(patient, mapping_name)
        if not isinstance(raw_mapping, dict):
            return PredicateResult(None, f"dated {attribute_name} information is not provided")
        days_ago = next(
            (value for key, value in raw_mapping.items() if str(key).casefold() == target), None
        )
        if not isinstance(days_ago, (int, float)) or isinstance(days_ago, bool) or days_ago < 0:
            return PredicateResult(None, f"valid days-ago value for {predicate.target} is not provided")
        assert predicate.temporal_window_days is not None
        return PredicateResult(
            days_ago <= predicate.temporal_window_days,
            f"{predicate.target} occurred {days_ago:g} days ago versus a "
            f"{predicate.temporal_window_days}-day window",
        )

    if predicate.operator not in {CriterionOperator.PRESENT, CriterionOperator.ABSENT}:
        return PredicateResult(None, f"operator {predicate.operator.value} is unsupported for facts")
    if target in positive_values and target in absent_values:
        return PredicateResult(None, f"{predicate.target} is both asserted present and absent")
    if target in positive_values:
        present: bool | None = True
    elif target in absent_values:
        present = False
    else:
        present = None
    if present is None:
        return PredicateResult(None, f"{predicate.target} presence or absence is not explicitly provided")
    expected_present = predicate.operator == CriterionOperator.PRESENT
    return PredicateResult(
        present == expected_present,
        f"{predicate.target} is explicitly {'present' if present else 'absent'}",
    )


def _evaluate_numeric(value: float | None, predicate: Predicate, label: str) -> PredicateResult:
    if value is None:
        return PredicateResult(None, f"{label} is not provided")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return PredicateResult(None, f"{label} is not numeric")
    operator = predicate.operator
    comparison = predicate.value
    if operator == CriterionOperator.BETWEEN:
        assert predicate.lower is not None and predicate.upper is not None
        lower_inclusive = predicate.include_lower is not False
        upper_inclusive = predicate.include_upper is not False
        lower_ok = value >= predicate.lower if lower_inclusive else value > predicate.lower
        upper_ok = value <= predicate.upper if upper_inclusive else value < predicate.upper
        return PredicateResult(
            lower_ok and upper_ok,
            f"{label} {value:g} is compared with "
            f"{'[' if lower_inclusive else '('}{predicate.lower:g}, {predicate.upper:g}"
            f"{']' if upper_inclusive else ')'}",
        )
    if not isinstance(comparison, (int, float)) or isinstance(comparison, bool):
        return PredicateResult(None, f"numeric comparison value for {label} is invalid")
    operations = {
        CriterionOperator.EQUALS: value == comparison,
        CriterionOperator.NOT_EQUALS: value != comparison,
        CriterionOperator.GREATER_THAN: value > comparison,
        CriterionOperator.GREATER_THAN_OR_EQUAL: value >= comparison,
        CriterionOperator.LESS_THAN: value < comparison,
        CriterionOperator.LESS_THAN_OR_EQUAL: value <= comparison,
    }
    result = operations.get(operator)
    if result is None:
        return PredicateResult(None, f"operator {operator.value} is unsupported for {label}")
    return PredicateResult(result, f"{label} {value:g} {operator.value} {comparison:g}")


def _evaluate_comparable(value: str, predicate: Predicate, label: str) -> PredicateResult:
    if not isinstance(predicate.value, str):
        return PredicateResult(None, f"comparison value for {label} is invalid")
    expected = predicate.value.casefold()
    if predicate.operator == CriterionOperator.EQUALS:
        return PredicateResult(value == expected, f"{label} {value!r} equals {expected!r}")
    if predicate.operator == CriterionOperator.NOT_EQUALS:
        return PredicateResult(value != expected, f"{label} {value!r} does not equal {expected!r}")
    return PredicateResult(None, f"operator {predicate.operator.value} is unsupported for {label}")


def missing_question(criterion: StructuredCriterion) -> str:
    predicate = criterion.predicate
    if predicate.operator in {CriterionOperator.ALL, CriterionOperator.ANY}:
        questions = [missing_question(_child_as_criterion(criterion, child, index)) for index, child in enumerate(predicate.children)]
        return " ".join(dict.fromkeys(questions))
    if predicate.attribute == CriterionAttribute.AGE_YEARS:
        return "What is the person's age in years?"
    if predicate.attribute == CriterionAttribute.SEX:
        return "What sex-related eligibility information is specified for the synthetic profile?"
    if predicate.attribute == CriterionAttribute.LABORATORY_VALUE:
        return f"What is the documented {predicate.target} laboratory value and unit?"
    if predicate.attribute in {
        CriterionAttribute.CONDITION,
        CriterionAttribute.MEDICATION,
        CriterionAttribute.PROCEDURE,
    }:
        temporal = " and when did it occur" if predicate.operator == CriterionOperator.WITHIN_DAYS else ""
        return f"Is {predicate.target} explicitly present or absent{temporal}?"
    return "Can study staff clarify this unsupported protocol requirement?"


def _child_as_criterion(
    criterion: StructuredCriterion, child: Predicate, index: int
) -> StructuredCriterion:
    return criterion.model_copy(
        update={"criterion_id": f"{criterion.criterion_id}-child-{index}", "predicate": child}
    )
