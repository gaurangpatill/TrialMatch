from __future__ import annotations

from hypothesis import given, strategies as st

from backend.app.clinical.evaluator import evaluate_criterion, evaluate_predicate
from backend.app.clinical.models import (
    CriterionAttribute,
    CriterionClassification,
    CriterionOperator,
    CriterionStatus,
    Predicate,
    SyntheticPatient,
)


def patient(**overrides):
    values = {
        "profile_id": "synthetic-test",
        "synthetic": True,
        "age_years": None,
        "sex": None,
        "conditions": [],
        "medications": [],
        "procedures": [],
        "laboratory_values": {},
        "attributes": {},
    }
    values.update(overrides)
    return SyntheticPatient(**values)


def test_missing_patient_fact_is_unknown(criterion_factory):
    result = evaluate_criterion(criterion_factory(), patient())
    assert result.status == CriterionStatus.UNKNOWN
    assert "Insufficient" in result.explanation


@given(age=st.floats(min_value=0, max_value=125, allow_nan=False, allow_infinity=False))
def test_inclusive_age_boundary_is_deterministic(age):
    predicate = Predicate(
        attribute=CriterionAttribute.AGE_YEARS,
        operator=CriterionOperator.GREATER_THAN_OR_EQUAL,
        value=18,
    )
    first = evaluate_predicate(predicate, patient(age_years=age))
    second = evaluate_predicate(predicate, patient(age_years=age))
    assert first == second
    assert first.value is (age >= 18)


def test_exclusion_polarity_for_known_condition(criterion_factory):
    criterion = criterion_factory(
        classification=CriterionClassification.EXCLUSION,
        attribute=CriterionAttribute.CONDITION,
        operator=CriterionOperator.PRESENT,
        target="pregnancy",
        value=None,
        text="Pregnancy is an exclusion.",
    )
    assert evaluate_criterion(criterion, patient(conditions=["pregnancy"])).status == CriterionStatus.NOT_MET
    assert (
        evaluate_criterion(
            criterion, patient(attributes={"absent_conditions": ["pregnancy"]})
        ).status
        == CriterionStatus.MET
    )


def test_negated_condition_requires_explicit_absence(criterion_factory):
    criterion = criterion_factory(
        attribute=CriterionAttribute.CONDITION,
        operator=CriterionOperator.ABSENT,
        target="diabetes",
        value=None,
    )
    assert evaluate_criterion(criterion, patient()).status == CriterionStatus.UNKNOWN
    assert (
        evaluate_criterion(
            criterion, patient(attributes={"absent_conditions": ["diabetes"]})
        ).status
        == CriterionStatus.MET
    )


def test_compound_three_valued_logic(criterion_factory):
    age = Predicate(
        attribute=CriterionAttribute.AGE_YEARS,
        operator=CriterionOperator.GREATER_THAN_OR_EQUAL,
        value=18,
    )
    condition = Predicate(
        attribute=CriterionAttribute.CONDITION,
        operator=CriterionOperator.PRESENT,
        target="asthma",
    )
    all_criterion = criterion_factory(
        attribute=CriterionAttribute.UNSUPPORTED,
        operator=CriterionOperator.ALL,
        value=None,
        children=[age, condition],
    )
    assert evaluate_criterion(all_criterion, patient(age_years=30)).status == CriterionStatus.UNKNOWN
    assert (
        evaluate_criterion(all_criterion, patient(age_years=17, conditions=["asthma"])).status
        == CriterionStatus.NOT_MET
    )
    assert (
        evaluate_criterion(all_criterion, patient(age_years=30, conditions=["asthma"])).status
        == CriterionStatus.MET
    )


def test_bounded_duration_requires_dated_fact(criterion_factory):
    criterion = criterion_factory(
        classification=CriterionClassification.EXCLUSION,
        attribute=CriterionAttribute.PROCEDURE,
        operator=CriterionOperator.WITHIN_DAYS,
        target="major surgery",
        value=None,
        temporal_window_days=30,
        text="Major surgery within 30 days is excluded.",
    )
    assert (
        evaluate_criterion(criterion, patient(procedures=["major surgery"])).status
        == CriterionStatus.UNKNOWN
    )
    assert (
        evaluate_criterion(
            criterion,
            patient(
                procedures=["major surgery"],
                attributes={"procedure_days_ago": {"major surgery": 10}},
            ),
        ).status
        == CriterionStatus.NOT_MET
    )
    assert (
        evaluate_criterion(
            criterion,
            patient(
                procedures=["major surgery"],
                attributes={"procedure_days_ago": {"major surgery": 31}},
            ),
        ).status
        == CriterionStatus.MET
    )


def test_between_respects_open_and_closed_boundaries():
    predicate = Predicate(
        attribute=CriterionAttribute.AGE_YEARS,
        operator=CriterionOperator.BETWEEN,
        lower=18,
        upper=65,
        include_lower=False,
        include_upper=True,
    )
    assert evaluate_predicate(predicate, patient(age_years=18)).value is False
    assert evaluate_predicate(predicate, patient(age_years=65)).value is True


def test_unsupported_criterion_is_unknown(criterion_factory):
    criterion = criterion_factory(
        attribute=CriterionAttribute.UNSUPPORTED,
        operator=CriterionOperator.UNSUPPORTED,
        value=None,
    )
    assert evaluate_criterion(criterion, patient(age_years=40)).status == CriterionStatus.UNKNOWN
