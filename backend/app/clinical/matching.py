"""Preliminary synthetic-patient matching with evidence-linked explanations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from .database import ClinicalRepository
from .evaluator import evaluate_criterion, missing_question
from .models import (
    CriterionStatus,
    MatchResponse,
    ScreeningStatus,
    StructuredCriterion,
    SyntheticPatient,
    TrialMatchResult,
)


class MatchingService:
    def __init__(
        self,
        repository: ClinicalRepository,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(UTC))

    def match(
        self,
        patient: SyntheticPatient,
        *,
        trial_ids: list[str] | None = None,
        limit: int = 20,
    ) -> MatchResponse:
        studies = self.repository.get_studies(trial_ids, limit=limit)[:limit]
        results: list[TrialMatchResult] = []
        for study in studies:
            criteria = self.repository.get_criteria(study.nct_id)
            evaluations = [evaluate_criterion(criterion, patient) for criterion in criteria]
            mismatches = [
                evaluation.original_text
                for evaluation in evaluations
                if evaluation.status == CriterionStatus.NOT_MET
            ]
            unresolved = [
                evaluation.original_text
                for evaluation in evaluations
                if evaluation.status == CriterionStatus.UNKNOWN
            ]
            questions = [
                missing_question(criterion)
                for criterion, evaluation in zip(criteria, evaluations, strict=True)
                if evaluation.status == CriterionStatus.UNKNOWN
            ]
            contradictions = find_contradictions(criteria)
            unresolved.extend(contradictions)
            if mismatches:
                status = ScreeningStatus.KNOWN_MISMATCH
            elif evaluations and not unresolved and all(
                evaluation.status == CriterionStatus.MET for evaluation in evaluations
            ):
                status = ScreeningStatus.POTENTIAL_MATCH
            else:
                status = ScreeningStatus.UNRESOLVED
            if not criteria:
                unresolved.append("No validated structured eligibility criteria are cached for this study.")
                questions.append("Which protocol requirements should study staff review for this profile?")
            results.append(
                TrialMatchResult(
                    nct_id=study.nct_id,
                    title=study.title,
                    screening_status=status,
                    criteria=evaluations,
                    known_mismatches=list(dict.fromkeys(mismatches)),
                    unresolved_requirements=list(dict.fromkeys(unresolved)),
                    missing_questions=list(dict.fromkeys(questions)),
                    source_url=study.source_url,
                )
            )
        return MatchResponse(profile_id=patient.profile_id, results=results, generated_at=self.clock())


def find_contradictions(criteria: list[StructuredCriterion]) -> list[str]:
    """Surface identical predicates used with opposite source classifications."""

    classifications: dict[str, set[str]] = {}
    texts: dict[str, list[str]] = {}
    for criterion in criteria:
        key = criterion.predicate.model_dump_json(exclude_none=True)
        classifications.setdefault(key, set()).add(criterion.classification.value)
        texts.setdefault(key, []).append(criterion.original_text)
    warnings: list[str] = []
    for key, values in classifications.items():
        if values == {"inclusion", "exclusion"}:
            evidence = " | ".join(dict.fromkeys(texts[key]))
            warnings.append(f"Potentially contradictory source criteria require review: {evidence}")
    return warnings
