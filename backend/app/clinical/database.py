"""SQLite persistence for normalized studies, provenance, and extraction caches."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import IngestionReport, StructuredCriterion, Study


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS studies (
    nct_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    phases_json TEXT NOT NULL,
    eligibility_criteria TEXT,
    minimum_age TEXT,
    maximum_age TEXT,
    sex TEXT,
    locations_json TEXT NOT NULL,
    contacts_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studies_status_nct ON studies(overall_status, nct_id);
CREATE INDEX IF NOT EXISTS idx_studies_title ON studies(title);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    raw_record_count INTEGER NOT NULL,
    accepted_record_count INTEGER NOT NULL,
    duplicate_identifier_count INTEGER NOT NULL,
    missing_value_counts_json TEXT NOT NULL,
    excluded_records_json TEXT NOT NULL,
    errors_json TEXT NOT NULL,
    detail_requested_count INTEGER NOT NULL,
    detail_retrieved_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS criteria (
    criterion_id TEXT PRIMARY KEY,
    nct_id TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
    extraction_method TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_criteria_nct ON criteria(nct_id, extraction_method);

CREATE TABLE IF NOT EXISTS extraction_cache (
    cache_key TEXT PRIMARY KEY,
    nct_id TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
    source_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extraction_cache_nct ON extraction_cache(nct_id);
"""


class ClinicalRepository:
    """Small connection-per-operation repository suitable for one-process SQLite use."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            connection.commit()

    def upsert_studies(self, studies: Iterable[Study]) -> int:
        payloads = []
        for study in studies:
            payloads.append(
                (
                    study.nct_id,
                    study.title,
                    study.overall_status,
                    json.dumps(study.conditions),
                    json.dumps(study.phases),
                    study.eligibility_criteria,
                    study.minimum_age,
                    study.maximum_age,
                    study.sex,
                    json.dumps([item.model_dump(mode="json") for item in study.locations]),
                    json.dumps([item.model_dump(mode="json") for item in study.contacts]),
                    study.source_url,
                    study.retrieved_at.isoformat(),
                    study.source_hash,
                    json.dumps(study.raw_source, sort_keys=True),
                )
            )
        if not payloads:
            return 0
        with closing(self._connect()) as connection:
            connection.executemany(
                """
                INSERT INTO studies (
                    nct_id, title, overall_status, conditions_json, phases_json,
                    eligibility_criteria, minimum_age, maximum_age, sex,
                    locations_json, contacts_json, source_url, retrieved_at,
                    source_hash, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(nct_id) DO UPDATE SET
                    title=excluded.title,
                    overall_status=excluded.overall_status,
                    conditions_json=excluded.conditions_json,
                    phases_json=excluded.phases_json,
                    eligibility_criteria=excluded.eligibility_criteria,
                    minimum_age=excluded.minimum_age,
                    maximum_age=excluded.maximum_age,
                    sex=excluded.sex,
                    locations_json=excluded.locations_json,
                    contacts_json=excluded.contacts_json,
                    source_url=excluded.source_url,
                    retrieved_at=excluded.retrieved_at,
                    source_hash=excluded.source_hash,
                    raw_json=excluded.raw_json
                """,
                payloads,
            )
            connection.commit()
        return len(payloads)

    def save_ingestion_report(self, report: IngestionReport) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs (
                    source_url, started_at, completed_at, status, page_count,
                    raw_record_count, accepted_record_count, duplicate_identifier_count,
                    missing_value_counts_json, excluded_records_json, errors_json,
                    detail_requested_count, detail_retrieved_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.source_url,
                    report.started_at.isoformat(),
                    report.completed_at.isoformat(),
                    report.status.value,
                    report.page_count,
                    report.raw_record_count,
                    report.accepted_record_count,
                    report.duplicate_identifier_count,
                    json.dumps(report.missing_value_counts, sort_keys=True),
                    json.dumps(report.excluded_records, sort_keys=True),
                    json.dumps(report.errors),
                    report.detail_requested_count,
                    report.detail_retrieved_count,
                ),
            )
            connection.commit()

    def search_studies(
        self,
        *,
        query: str | None = None,
        condition: str | None = None,
        phase: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Study], int]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM studies ORDER BY nct_id").fetchall()
        studies = [self._row_to_study(row) for row in rows]
        if query:
            needle = query.casefold()
            studies = [
                study
                for study in studies
                if needle in study.title.casefold()
                or any(needle in item.casefold() for item in study.conditions)
            ]
        if condition:
            needle = condition.strip().casefold()
            studies = [
                study for study in studies if any(item.casefold() == needle for item in study.conditions)
            ]
        if phase:
            needle = phase.strip().casefold()
            studies = [study for study in studies if any(item.casefold() == needle for item in study.phases)]
        total = len(studies)
        start = (page - 1) * page_size
        return studies[start : start + page_size], total

    def get_studies(self, nct_ids: list[str] | None = None, limit: int = 20) -> list[Study]:
        with closing(self._connect()) as connection:
            if nct_ids is None:
                rows = connection.execute(
                    "SELECT * FROM studies ORDER BY nct_id LIMIT ?", (limit,)
                ).fetchall()
            elif not nct_ids:
                return []
            else:
                placeholders = ",".join("?" for _ in nct_ids)
                rows = connection.execute(
                    f"SELECT * FROM studies WHERE nct_id IN ({placeholders}) ORDER BY nct_id",
                    nct_ids,
                ).fetchall()
        return [self._row_to_study(row) for row in rows]

    def latest_retrieved_at(self) -> datetime | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT MAX(retrieved_at) AS value FROM studies").fetchone()
        return datetime.fromisoformat(row["value"]) if row and row["value"] else None

    def replace_criteria(self, nct_id: str, method: str, criteria: list[StructuredCriterion]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM criteria WHERE nct_id = ? AND extraction_method = ?", (nct_id, method)
            )
            connection.executemany(
                "INSERT INTO criteria (criterion_id, nct_id, extraction_method, payload_json) VALUES (?, ?, ?, ?)",
                [
                    (
                        criterion.criterion_id,
                        criterion.nct_id,
                        criterion.extraction_method,
                        criterion.model_dump_json(),
                    )
                    for criterion in criteria
                ],
            )
            connection.commit()

    def get_criteria(self, nct_id: str) -> list[StructuredCriterion]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM criteria WHERE nct_id = ? ORDER BY criterion_id", (nct_id,)
            ).fetchall()
        return [StructuredCriterion.model_validate_json(row["payload_json"]) for row in rows]

    def get_cached_extraction(self, cache_key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM extraction_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save_extraction_cache(
        self,
        *,
        cache_key: str,
        nct_id: str,
        source_hash: str,
        provider: str,
        model: str,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO extraction_cache (
                    cache_key, nct_id, source_hash, provider, model, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    nct_id,
                    source_hash,
                    provider,
                    model,
                    json.dumps(payload, sort_keys=True),
                    created_at.isoformat(),
                ),
            )
            connection.commit()

    @staticmethod
    def _row_to_study(row: sqlite3.Row) -> Study:
        return Study.model_validate(
            {
                "nct_id": row["nct_id"],
                "title": row["title"],
                "overall_status": row["overall_status"],
                "conditions": json.loads(row["conditions_json"]),
                "phases": json.loads(row["phases_json"]),
                "eligibility_criteria": row["eligibility_criteria"],
                "minimum_age": row["minimum_age"],
                "maximum_age": row["maximum_age"],
                "sex": row["sex"],
                "locations": json.loads(row["locations_json"]),
                "contacts": json.loads(row["contacts_json"]),
                "source_url": row["source_url"],
                "retrieved_at": row["retrieved_at"],
                "source_hash": row["source_hash"],
                "raw_source": json.loads(row["raw_json"]),
            }
        )
