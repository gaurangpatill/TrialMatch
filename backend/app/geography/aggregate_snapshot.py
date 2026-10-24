"""Canonical persisted municipality EJ-subset aggregates and provenance."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from .client import MassGISClient, MassGISClientError
from .ingestion import GeographyIngestionService
from .models import AcquisitionReport, MunicipalityEJSubsetAggregate, StrictModel
from .transform import aggregate_municipalities, normalize_records

DEFAULT_AGGREGATE_SNAPSHOT_PATH = (
    Path(__file__).with_name("data") / "municipality_ej_subset_aggregates.json"
)


class MunicipalityAggregateSnapshot(StrictModel):
    """Servable aggregates plus the exact source acquisition evidence."""

    schema_version: Literal["municipality_ej_subset_aggregates_v1"] = (
        "municipality_ej_subset_aggregates_v1"
    )
    report: AcquisitionReport
    municipalities: tuple[MunicipalityEJSubsetAggregate, ...] = Field(min_length=1)


def save_aggregate_snapshot(
    snapshot: MunicipalityAggregateSnapshot,
    destination: str | Path = DEFAULT_AGGREGATE_SNAPSHOT_PATH,
) -> int:
    """Atomically write canonical compact JSON and return its byte size."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            snapshot.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return len(payload)


def load_aggregate_snapshot(
    source: str | Path = DEFAULT_AGGREGATE_SNAPSHOT_PATH,
) -> MunicipalityAggregateSnapshot:
    return MunicipalityAggregateSnapshot.model_validate_json(
        Path(source).read_text(encoding="utf-8")
    )


def regenerate_official_aggregate_snapshot(
    destination: str | Path = DEFAULT_AGGREGATE_SNAPSHOT_PATH,
    *,
    page_size: int = 500,
) -> MunicipalityAggregateSnapshot:
    """Acquire genuine attributes once; requests only read the resulting snapshot."""

    with MassGISClient() as client:
        result = GeographyIngestionService(client, page_size=page_size).acquire()
    normalized = normalize_records(result.records)
    if not result.report.complete or normalized.quarantined:
        raise MassGISClientError(
            "attribute acquisition did not reconcile completely; snapshot not replaced"
        )
    snapshot = MunicipalityAggregateSnapshot(
        report=result.report,
        municipalities=aggregate_municipalities(normalized.records),
    )
    save_aggregate_snapshot(snapshot, destination)
    return snapshot
