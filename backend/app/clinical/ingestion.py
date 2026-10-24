"""ClinicalTrials.gov ingestion orchestration and provenance reporting."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import ClinicalTrialsClient, PartialFetchError
from .database import ClinicalRepository
from .models import DetailRetrievalStatus, IngestionReport, IngestionStatus, Study
from .normalize import StudyNormalizationError, normalize_study, source_missing_values, source_structured_criteria


class ClinicalIngestionService:
    def __init__(self, client: ClinicalTrialsClient, repository: ClinicalRepository):
        self.client = client
        self.repository = repository

    async def ingest(
        self,
        *,
        page_size: int = 1000,
        detail_limit: int = 20,
        detail_ids: list[str] | None = None,
        detail_conditions: list[str] | None = None,
        detail_delay_seconds: float = 0,
    ) -> IngestionReport:
        started_at = datetime.now(UTC)
        errors: list[str] = []
        exclusions: list[dict[str, str]] = []
        source_complete = True
        try:
            fetched = await self.client.fetch_all_recruiting_massachusetts(page_size=page_size)
            records = fetched.records
            page_count = fetched.page_count
            duplicates = fetched.duplicate_identifier_count
        except PartialFetchError as exc:
            records = exc.records
            page_count = exc.page_count
            duplicates = exc.duplicate_identifier_count
            errors.append(str(exc))
            source_complete = False

        retrieval_time = datetime.now(UTC)
        normalized: dict[str, Study] = {}
        missing_counts: Counter[str] = Counter()
        for index, record in enumerate(records):
            try:
                study = normalize_study(record, retrieval_time)
            except StudyNormalizationError as exc:
                exclusions.append({"record": str(index), "reason": str(exc)})
                continue
            if study.nct_id in normalized:
                duplicates += 1
                continue
            normalized[study.nct_id] = study
            missing_counts.update(source_missing_values(study))

        if detail_ids is not None:
            selected_ids = [nct_id for nct_id in detail_ids if nct_id in normalized]
        else:
            detail_candidates = sorted(normalized.values(), key=lambda study: study.nct_id)
            if detail_conditions:
                needles = [value.strip().casefold() for value in detail_conditions if value.strip()]
                detail_candidates = [
                    study
                    for study in detail_candidates
                    if any(
                        needle in study.title.casefold()
                        or any(needle in condition.casefold() for condition in study.conditions)
                        for needle in needles
                    )
                ]
            selected_ids = [study.nct_id for study in detail_candidates[:detail_limit]]
        detail_retrieved = 0
        for index, nct_id in enumerate(selected_ids):
            if index and detail_delay_seconds:
                await asyncio.sleep(detail_delay_seconds)
            try:
                detail = await self.client.fetch_detail(nct_id)
                detailed_study = normalize_study(
                    detail.record,
                    detail.retrieved_at,
                    detail_status=DetailRetrievalStatus.RETRIEVED,
                )
                if detailed_study.nct_id != nct_id:
                    raise StudyNormalizationError(
                        f"detail identifier mismatch: requested {nct_id}, received {detailed_study.nct_id}"
                    )
                previous_missing = source_missing_values(normalized[nct_id])
                updated_missing = source_missing_values(detailed_study)
                missing_counts.subtract(previous_missing)
                missing_counts.update(updated_missing)
                normalized[nct_id] = detailed_study
                detail_retrieved += 1
            except Exception as exc:  # boundary: every selected source failure belongs in run provenance
                errors.append(f"detail {nct_id}: {type(exc).__name__}: {exc}")

        studies = list(normalized.values())
        publication_complete = (
            bool(studies)
            and source_complete
            and not exclusions
            and detail_retrieved == len(selected_ids)
        )
        if publication_complete:
            source_criteria = {
                study.nct_id: source_structured_criteria(study, created_at=retrieval_time)
                for study in studies
            }
            self.repository.publish_complete_snapshot(studies, source_criteria)

        if not studies:
            status = IngestionStatus.FAILED
        elif publication_complete:
            status = IngestionStatus.COMPLETE
        else:
            status = IngestionStatus.PARTIAL
        report = IngestionReport(
            source_url=self.client.list_query_url(page_size),
            effective_page_size=page_size,
            pagination_completed=source_complete,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            status=status,
            page_count=page_count,
            raw_record_count=len(records) + duplicates,
            accepted_record_count=len(studies),
            duplicate_identifier_count=duplicates,
            missing_value_counts={key: max(0, value) for key, value in sorted(missing_counts.items())},
            excluded_records=exclusions,
            errors=errors,
            detail_requested_count=len(selected_ids),
            detail_retrieved_count=detail_retrieved,
        )
        self.repository.save_ingestion_report(report)
        return report


def write_report(report: IngestionReport, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(report.model_dump_json(indent=2))
    temporary.replace(destination)


def update_manifest(report: IngestionReport, path: str | Path) -> None:
    """Update only the ClinicalTrials.gov acquisition entry from an observed run."""

    manifest_path = Path(path)
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    source = next(
        item for item in manifest["sources"] if item["id"] == "clinicaltrials-gov-ma-recruiting"
    )
    source["acquisition"] = {
        "status": report.status.value,
        "acquired_at_utc": report.completed_at.isoformat(),
        "observed_record_count": report.raw_record_count,
        "accepted_record_count": report.accepted_record_count,
        "duplicate_identifier_count": report.duplicate_identifier_count,
        "missing_value_counts": report.missing_value_counts,
        "schema_valid": report.pagination_completed and not report.excluded_records,
        "raw_sha256": None,
        "effective_query_url": report.source_url,
        "effective_page_size": report.effective_page_size,
        "page_count": report.page_count,
        "pagination_completed": report.pagination_completed,
        "filters_or_exclusions": [
            "query.locn=Massachusetts",
            "filter.overallStatus=RECRUITING",
            f"excluded_source_records={len(report.excluded_records)}",
            f"expanded_detail_records={report.detail_retrieved_count}",
        ],
    }
    manifest["last_updated_utc"] = report.completed_at.isoformat()
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(manifest_path)
