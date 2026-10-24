"""Complete, evidence-producing ArcGIS offset pagination."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from .client import MassGISClient, MassGISClientError
from .models import AcquisitionReport, IngestionResult, QuarantinedRecord, RawEJAttributes
from .transform import REQUIRED_ATTRIBUTES, validate_raw_attributes

WHERE_EJ_YES = "EJ='Yes'"


class GeographyIngestionService:
    def __init__(self, client: MassGISClient, *, page_size: int = 100) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.client = client
        self.page_size = page_size

    def acquire(self) -> IngestionResult:
        started = datetime.now(timezone.utc)
        metadata = self.client.get_metadata()
        object_id_field = metadata.object_id_field
        partial_failures: list[str] = []
        if not object_id_field:
            raise MassGISClientError("layer metadata does not identify an object ID field")
        metadata_names = {field.name for field in metadata.fields}
        absent_metadata_fields = [
            field for field in (*REQUIRED_ATTRIBUTES, object_id_field) if metadata_names and field not in metadata_names
        ]
        if absent_metadata_fields:
            raise MassGISClientError(
                f"layer metadata is missing required field(s): {', '.join(absent_metadata_fields)}"
            )
        expected_count = self.client.get_count(WHERE_EJ_YES)
        effective_page_size = min(self.page_size, metadata.maxRecordCount or self.page_size)
        out_fields = (*REQUIRED_ATTRIBUTES, object_id_field)
        base_params: dict[str, str | int | bool] = {
            "f": "json",
            "where": WHERE_EJ_YES,
            "outFields": ",".join(out_fields),
            "returnGeometry": "false",
            "resultRecordCount": effective_page_size,
        }
        if metadata.supports_order_by:
            base_params["orderByFields"] = f"{object_id_field} ASC"

        offset = 0
        fetched_count = 0
        page_count = 0
        records: list[RawEJAttributes] = []
        seen_ids: set[str] = set()
        duplicates: list[str] = []
        quarantined: list[QuarantinedRecord] = []
        fingerprints: set[str] = set()
        termination_reason = "unknown"
        clean_termination = False

        while True:
            params = {**base_params, "resultOffset": offset}
            try:
                page = self.client.query_page(params)
            except MassGISClientError as exc:
                partial_failures.append(str(exc))
                termination_reason = "source request failed before pagination completed"
                break
            page_count += 1
            canonical = json.dumps(
                [feature.attributes for feature in page.features],
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if page.features and fingerprint in fingerprints:
                termination_reason = "repeated page fingerprint detected"
                partial_failures.append(termination_reason)
                break
            fingerprints.add(fingerprint)

            page_length = len(page.features)
            for index, feature in enumerate(page.features):
                fetched_count += 1
                raw_id = feature.attributes.get(object_id_field)
                source_id = None if raw_id is None else str(raw_id).strip() or None
                try:
                    record = validate_raw_attributes(feature.attributes, object_id_field)
                except (ValueError, ValidationError) as exc:
                    quarantined.append(
                        QuarantinedRecord(
                            page_offset=offset,
                            record_index=index,
                            source_id=source_id,
                            reason=str(exc),
                        )
                    )
                    continue
                if record.source_id in seen_ids:
                    duplicates.append(record.source_id)
                    continue
                seen_ids.add(record.source_id)
                records.append(record)

            offset += page_length
            if page.exceededTransferLimit:
                if page_length == 0:
                    termination_reason = "transfer limit asserted on empty page"
                    partial_failures.append(termination_reason)
                    break
                continue
            if expected_count is not None and fetched_count < expected_count:
                if page_length == 0:
                    termination_reason = "empty page before expected count was fetched"
                    partial_failures.append(termination_reason)
                    break
                continue
            if expected_count is None and page_length == effective_page_size:
                continue
            clean_termination = True
            termination_reason = "expected count fetched and transfer limit cleared"
            break

        accepted_count = len(records)
        missing_value_counts = {
            field: sum(getattr(record, field) is None for record in records)
            for field in REQUIRED_ATTRIBUTES
        }
        counts_match = expected_count is None or fetched_count == expected_count
        unique_match = expected_count is None or accepted_count == expected_count
        complete = (
            clean_termination
            and counts_match
            and unique_match
            and not duplicates
            and not quarantined
            and not partial_failures
        )
        if clean_termination and not complete:
            termination_reason = "retrieval ended but expected/unique/schema reconciliation failed"
        finished = datetime.now(timezone.utc)
        report = AcquisitionReport(
            source_url=self.client.layer_url,
            object_id_field=object_id_field,
            out_fields=out_fields,
            page_size=effective_page_size,
            started_at_utc=started,
            finished_at_utc=finished,
            expected_source_count=expected_count,
            fetched_record_count=fetched_count,
            unique_accepted_count=accepted_count,
            duplicate_count=len(duplicates),
            invalid_quarantined_count=len(quarantined),
            page_count=page_count,
            retry_count=self.client.retry_count,
            complete=complete,
            termination_reason=termination_reason,
            query_parameters=base_params,
            missing_value_counts=missing_value_counts,
            transformations=("source object IDs canonicalized as non-empty strings",),
            filters_and_exclusions=(
                "source query restricted to EJ='Yes'",
                "duplicate source IDs excluded after first occurrence",
                "malformed records quarantined rather than fabricated",
            ),
            duplicate_source_ids=tuple(duplicates),
            quarantined=tuple(quarantined),
            partial_failures=tuple(partial_failures),
        )
        return IngestionResult(records=tuple(records), report=report)
