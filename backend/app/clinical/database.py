"""SQLite persistence for normalized studies, provenance, and extraction caches."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import DetailRetrievalStatus, IngestionReport, StructuredCriterion, Study


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
    raw_json TEXT NOT NULL,
    detail_status TEXT NOT NULL DEFAULT 'not_retrieved',
    detail_attempted_at TEXT,
    detail_error_code TEXT
);
CREATE INDEX IF NOT EXISTS idx_studies_status_nct ON studies(overall_status, nct_id);
CREATE INDEX IF NOT EXISTS idx_studies_title ON studies(title);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    effective_page_size INTEGER NOT NULL DEFAULT 20,
    pagination_completed INTEGER NOT NULL DEFAULT 0,
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
    created_at TEXT NOT NULL,
    coverage_verified INTEGER NOT NULL DEFAULT 0,
    coverage_verification_method TEXT,
    coverage_verified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_extraction_cache_nct ON extraction_cache(nct_id);

CREATE TABLE IF NOT EXISTS extraction_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nct_id TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
    source_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extraction_attempts_current
ON extraction_attempts(nct_id, source_hash, created_at);
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
            study_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(studies)")
            }
            if "detail_status" not in study_columns:
                connection.execute(
                    "ALTER TABLE studies ADD COLUMN detail_status TEXT NOT NULL DEFAULT 'not_retrieved'"
                )
            if "detail_attempted_at" not in study_columns:
                connection.execute("ALTER TABLE studies ADD COLUMN detail_attempted_at TEXT")
            if "detail_error_code" not in study_columns:
                connection.execute("ALTER TABLE studies ADD COLUMN detail_error_code TEXT")
            # Preserve previously expanded rows when migrating an existing database. The
            # indexed list payload contains none of these detail-only source modules.
            connection.execute(
                """
                UPDATE studies
                SET detail_status = 'retrieved', detail_attempted_at = retrieved_at
                WHERE detail_status = 'not_retrieved'
                  AND (raw_json LIKE '%\"eligibilityModule\"%'
                       OR raw_json LIKE '%\"contactsLocationsModule\"%'
                       OR raw_json LIKE '%\"descriptionModule\"%')
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(ingestion_runs)")
            }
            if "effective_page_size" not in columns:
                connection.execute(
                    "ALTER TABLE ingestion_runs ADD COLUMN effective_page_size INTEGER NOT NULL DEFAULT 20"
                )
            if "pagination_completed" not in columns:
                connection.execute(
                    "ALTER TABLE ingestion_runs ADD COLUMN pagination_completed INTEGER NOT NULL DEFAULT 0"
                )
            cache_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(extraction_cache)")
            }
            if "coverage_verified" not in cache_columns:
                connection.execute(
                    "ALTER TABLE extraction_cache ADD COLUMN coverage_verified INTEGER NOT NULL DEFAULT 0"
                )
            if "coverage_verification_method" not in cache_columns:
                connection.execute(
                    "ALTER TABLE extraction_cache ADD COLUMN coverage_verification_method TEXT"
                )
            if "coverage_verified_at" not in cache_columns:
                connection.execute(
                    "ALTER TABLE extraction_cache ADD COLUMN coverage_verified_at TEXT"
                )
            connection.commit()

    @staticmethod
    def _study_payloads(studies: Iterable[Study]) -> list[tuple[Any, ...]]:
        return [
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
                study.detail_status.value,
                study.detail_attempted_at.isoformat() if study.detail_attempted_at else None,
                study.detail_error_code,
            )
            for study in studies
        ]

    @staticmethod
    def _upsert_on_connection(
        connection: sqlite3.Connection, payloads: list[tuple[Any, ...]]
    ) -> None:
        connection.executemany(
            """
            INSERT INTO studies (
                nct_id, title, overall_status, conditions_json, phases_json,
                eligibility_criteria, minimum_age, maximum_age, sex,
                locations_json, contacts_json, source_url, retrieved_at,
                source_hash, raw_json, detail_status, detail_attempted_at,
                detail_error_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nct_id) DO UPDATE SET
                title=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.title ELSE excluded.title END,
                overall_status=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.overall_status ELSE excluded.overall_status END,
                conditions_json=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.conditions_json ELSE excluded.conditions_json END,
                phases_json=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.phases_json ELSE excluded.phases_json END,
                eligibility_criteria=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.eligibility_criteria ELSE excluded.eligibility_criteria END,
                minimum_age=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.minimum_age ELSE excluded.minimum_age END,
                maximum_age=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.maximum_age ELSE excluded.maximum_age END,
                sex=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.sex ELSE excluded.sex END,
                locations_json=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.locations_json ELSE excluded.locations_json END,
                contacts_json=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.contacts_json ELSE excluded.contacts_json END,
                source_url=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.source_url ELSE excluded.source_url END,
                retrieved_at=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.retrieved_at ELSE excluded.retrieved_at END,
                source_hash=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.source_hash ELSE excluded.source_hash END,
                raw_json=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.raw_json ELSE excluded.raw_json END,
                detail_status=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.detail_status ELSE excluded.detail_status END,
                detail_attempted_at=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.detail_attempted_at ELSE excluded.detail_attempted_at END,
                detail_error_code=CASE WHEN studies.detail_status = 'retrieved'
                               AND excluded.detail_status != 'retrieved'
                           THEN studies.detail_error_code ELSE excluded.detail_error_code END
            """,
            payloads,
        )

    def upsert_studies(self, studies: Iterable[Study]) -> int:
        payloads = self._study_payloads(studies)
        if not payloads:
            return 0
        with closing(self._connect()) as connection:
            self._upsert_on_connection(connection, payloads)
            connection.commit()
        return len(payloads)

    def replace_complete_snapshot(self, studies: Iterable[Study]) -> int:
        """Atomically upsert a complete recruiting snapshot and remove stale studies."""

        payloads = self._study_payloads(studies)
        if not payloads:
            raise ValueError("refusing to replace a complete snapshot with no accepted studies")
        identifiers = [(payload[0],) for payload in payloads]
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TEMP TABLE current_snapshot_ids (nct_id TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO current_snapshot_ids (nct_id) VALUES (?)", identifiers
            )
            self._upsert_on_connection(connection, payloads)
            connection.execute(
                "DELETE FROM studies WHERE nct_id NOT IN (SELECT nct_id FROM current_snapshot_ids)"
            )
            connection.commit()
        return len(payloads)

    def publish_complete_snapshot(
        self,
        studies: Iterable[Study],
        source_criteria: dict[str, list[StructuredCriterion]],
    ) -> int:
        """Atomically publish a complete study snapshot and all source-derived rules."""

        studies_list = list(studies)
        payloads = self._study_payloads(studies_list)
        if not payloads:
            raise ValueError("refusing to publish an empty complete snapshot")
        study_by_id = {study.nct_id: study for study in studies_list}
        if len(study_by_id) != len(studies_list):
            raise ValueError("complete snapshot contains duplicate NCT identifiers")
        criteria = [item for values in source_criteria.values() for item in values]
        for criterion in criteria:
            study = study_by_id.get(criterion.nct_id)
            if study is None:
                raise ValueError("source criterion references a study outside the snapshot")
            if criterion.extraction_method != "source_structured":
                raise ValueError("snapshot publication accepts only source_structured criteria")
            if criterion.source_hash != study.source_hash:
                raise ValueError("source criterion hash must match its study")
        identifiers = [(study.nct_id,) for study in studies_list]
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TEMP TABLE published_snapshot_ids (nct_id TEXT PRIMARY KEY)")
            connection.execute("CREATE TEMP TABLE expanded_snapshot_ids (nct_id TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO published_snapshot_ids (nct_id) VALUES (?)", identifiers
            )
            connection.executemany(
                "INSERT INTO expanded_snapshot_ids (nct_id) VALUES (?)",
                [
                    (study.nct_id,)
                    for study in studies_list
                    if study.detail_status == DetailRetrievalStatus.RETRIEVED
                ],
            )
            self._upsert_on_connection(connection, payloads)
            connection.execute(
                "DELETE FROM studies WHERE nct_id NOT IN (SELECT nct_id FROM published_snapshot_ids)"
            )
            # A list-only snapshot must not erase source-structured rules belonging to a
            # previously expanded record that the upsert deliberately preserved.
            connection.execute(
                """
                DELETE FROM criteria
                WHERE extraction_method = 'source_structured'
                  AND nct_id IN (SELECT nct_id FROM expanded_snapshot_ids)
                """
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
        return len(payloads)

    def save_ingestion_report(self, report: IngestionReport) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs (
                    source_url, effective_page_size, pagination_completed,
                    started_at, completed_at, status, page_count,
                    raw_record_count, accepted_record_count, duplicate_identifier_count,
                    missing_value_counts_json, excluded_records_json, errors_json,
                    detail_requested_count, detail_retrieved_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.source_url,
                    report.effective_page_size,
                    int(report.pagination_completed),
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
        age_years: float | None = None,
        location: str | None = None,
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
        if age_years is not None:
            studies = [
                study
                for study in studies
                if (_age_to_years(study.minimum_age) is not None)
                and (_age_to_years(study.maximum_age) is not None)
                and age_years >= _age_to_years(study.minimum_age)  # type: ignore[operator]
                and age_years <= _age_to_years(study.maximum_age)  # type: ignore[operator]
            ]
        if location:
            needle = location.strip().casefold()
            studies = [
                study
                for study in studies
                if any(
                    needle in (value or "").casefold()
                    for item in study.locations
                    for value in (item.facility, item.city, item.state, item.country)
                )
            ]
        studies.sort(
            key=lambda study: (
                study.detail_status != DetailRetrievalStatus.RETRIEVED,
                study.nct_id,
            )
        )
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

    def get_study(self, nct_id: str) -> Study | None:
        studies = self.get_studies([nct_id], limit=1)
        return studies[0] if studies else None

    def record_detail_failure(self, nct_id: str, attempted_at: datetime, error_code: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE studies
                SET detail_status = CASE WHEN detail_status = 'retrieved'
                                         THEN detail_status ELSE 'retrieval_failed' END,
                    detail_attempted_at = ?,
                    detail_error_code = ?
                WHERE nct_id = ?
                """,
                (attempted_at.isoformat(), error_code, nct_id),
            )
            connection.commit()

    def latest_retrieved_at(self) -> datetime | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT MAX(retrieved_at) AS value FROM studies").fetchone()
        return datetime.fromisoformat(row["value"]) if row and row["value"] else None

    def replace_criteria(self, nct_id: str, method: str, criteria: list[StructuredCriterion]) -> None:
        if any(criterion.extraction_method != method for criterion in criteria):
            raise ValueError("criterion extraction_method must match replacement method")
        if any(criterion.nct_id != nct_id for criterion in criteria):
            raise ValueError("criterion nct_id must match replacement study")
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

    def get_criteria(
        self, nct_id: str, *, source_hash: str | None = None
    ) -> list[StructuredCriterion]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM criteria WHERE nct_id = ? ORDER BY criterion_id", (nct_id,)
            ).fetchall()
        criteria = [StructuredCriterion.model_validate_json(row["payload_json"]) for row in rows]
        return [item for item in criteria if source_hash is None or item.source_hash == source_hash]

    def existing_study_ids(self, nct_ids: list[str]) -> set[str]:
        if not nct_ids:
            return set()
        placeholders = ",".join("?" for _ in nct_ids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT nct_id FROM studies WHERE nct_id IN ({placeholders})", nct_ids
            ).fetchall()
        return {row["nct_id"] for row in rows}

    def get_cached_extraction(self, cache_key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM extraction_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def publish_extraction(
        self,
        *,
        cache_key: str,
        nct_id: str,
        source_hash: str,
        provider: str,
        model: str,
        schema_version: str,
        prompt_version: str,
        payload: dict[str, Any],
        criteria: list[StructuredCriterion],
        created_at: datetime,
    ) -> None:
        """Atomically publish validated extraction cache, criteria, and accepted attempt."""

        if any(
            item.nct_id != nct_id
            or item.source_hash != source_hash
            or item.extraction_method != "llm"
            for item in criteria
        ):
            raise ValueError("published criteria must match the extraction generation")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT source_hash FROM studies WHERE nct_id = ?", (nct_id,)
            ).fetchone()
            if current is None or current["source_hash"] != source_hash:
                raise ValueError("cannot publish extraction for a stale or missing study")
            existing_payloads = connection.execute(
                """
                SELECT payload_json, coverage_verified FROM extraction_cache
                WHERE nct_id = ? AND source_hash = ?
                """,
                (nct_id, source_hash),
            ).fetchall()
            existing_complete = any(
                bool(row["coverage_verified"])
                and json.loads(row["payload_json"]).get("coverage", {}).get("status") == "complete"
                for row in existing_payloads
            )
            incoming_status = payload.get("coverage", {}).get("status")
            if existing_complete and incoming_status != "complete":
                raise ValueError(
                    "refusing to replace complete current-source coverage with incomplete coverage"
                )
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
            connection.execute(
                "DELETE FROM criteria WHERE nct_id = ? AND extraction_method = 'llm'", (nct_id,)
            )
            connection.executemany(
                "INSERT INTO criteria (criterion_id, nct_id, extraction_method, payload_json) VALUES (?, ?, ?, ?)",
                [
                    (item.criterion_id, item.nct_id, item.extraction_method, item.model_dump_json())
                    for item in criteria
                ],
            )
            connection.execute(
                "DELETE FROM extraction_cache WHERE nct_id = ? AND cache_key != ?",
                (nct_id, cache_key),
            )
            connection.execute(
                """
                INSERT INTO extraction_attempts (
                    nct_id, source_hash, provider, model, schema_version,
                    prompt_version, status, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'accepted', NULL, ?)
                """,
                (
                    nct_id,
                    source_hash,
                    provider,
                    model,
                    schema_version,
                    prompt_version,
                    created_at.isoformat(),
                ),
            )
            connection.commit()

    def delete_extraction_cache(self, cache_key: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM extraction_cache WHERE cache_key = ?", (cache_key,))
            connection.commit()

    def record_extraction_attempt(
        self,
        *,
        nct_id: str,
        source_hash: str,
        provider: str,
        model: str,
        schema_version: str,
        prompt_version: str,
        status: str,
        error: str,
        created_at: datetime,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO extraction_attempts (
                    nct_id, source_hash, provider, model, schema_version,
                    prompt_version, status, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nct_id,
                    source_hash,
                    provider,
                    model,
                    schema_version,
                    prompt_version,
                    status,
                    error,
                    created_at.isoformat(),
                ),
            )
            connection.commit()

    def approve_extraction_coverage(
        self,
        cache_key: str,
        *,
        verification_method: str,
        verified_at: datetime,
    ) -> None:
        allowed = {"manual_protocol_review", "deterministic_test_fixture"}
        if verification_method not in allowed:
            raise ValueError("unsupported independent coverage verification method")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM extraction_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
            if row is None:
                raise ValueError("extraction generation does not exist")
            payload = json.loads(row["payload_json"])
            if payload.get("coverage", {}).get("status") != "complete":
                raise ValueError("only provider-declared complete coverage can be independently verified")
            connection.execute(
                """
                UPDATE extraction_cache
                SET coverage_verified = 1,
                    coverage_verification_method = ?,
                    coverage_verified_at = ?
                WHERE cache_key = ?
                """,
                (verification_method, verified_at.isoformat(), cache_key),
            )
            connection.commit()

    def get_extraction_state(
        self, nct_id: str, source_hash: str
    ) -> tuple[str, dict[str, Any] | None, bool, str | None]:
        with closing(self._connect()) as connection:
            accepted = connection.execute(
                """
                SELECT payload_json, coverage_verified, coverage_verification_method
                FROM extraction_cache
                WHERE nct_id = ? AND source_hash = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (nct_id, source_hash),
            ).fetchone()
            if accepted:
                try:
                    return (
                        "accepted",
                        json.loads(accepted["payload_json"]),
                        bool(accepted["coverage_verified"]),
                        accepted["coverage_verification_method"],
                    )
                except json.JSONDecodeError:
                    return "failed", None, False, None
            attempt = connection.execute(
                """
                SELECT status FROM extraction_attempts
                WHERE nct_id = ? AND source_hash = ?
                ORDER BY id DESC LIMIT 1
                """,
                (nct_id, source_hash),
            ).fetchone()
            if attempt and attempt["status"] != "accepted":
                return "failed", None, False, None
            stale = connection.execute(
                """
                SELECT 1 FROM extraction_cache
                WHERE nct_id = ? AND source_hash != ? LIMIT 1
                """,
                (nct_id, source_hash),
            ).fetchone()
        return ("stale", None, False, None) if stale else ("not_attempted", None, False, None)

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
                "detail_status": row["detail_status"],
                "detail_attempted_at": row["detail_attempted_at"],
                "detail_error_code": row["detail_error_code"],
            }
        )


def _age_to_years(value: str | None) -> float | None:
    if not value:
        return None
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s+(Year|Years|Month|Months|Week|Weeks|Day|Days)\s*",
        value,
    )
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).casefold()
    if unit.startswith("year"):
        return number
    if unit.startswith("month"):
        return number / 12
    if unit.startswith("week"):
        return number / 52.1429
    return number / 365.2425
