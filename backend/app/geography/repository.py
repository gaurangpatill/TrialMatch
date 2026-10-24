"""SQLite persistence boundary for normalized geography and acquisition evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Protocol

from .models import (
    AcquisitionReport,
    IngestionResult,
    MunicipalityEJSubsetAggregate,
    NormalizedBlockGroup,
)


class GeographyRepository(Protocol):
    def initialize(self) -> None: ...
    def save_acquisition_report(self, report: AcquisitionReport) -> int: ...
    def replace_block_groups(self, records: tuple[NormalizedBlockGroup, ...]) -> None: ...
    def replace_municipalities(self, records: tuple[MunicipalityEJSubsetAggregate, ...]) -> None: ...
    def cache_raw_records(self, result: IngestionResult, destination: str | Path) -> str: ...


class SQLiteGeographyRepository:
    """Small explicit schema; caller controls transaction-sized replacement operations."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS geography_acquisition_runs (
                    id INTEGER PRIMARY KEY,
                    started_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    object_id_field TEXT,
                    expected_source_count INTEGER,
                    fetched_record_count INTEGER NOT NULL,
                    unique_accepted_count INTEGER NOT NULL,
                    duplicate_count INTEGER NOT NULL,
                    invalid_quarantined_count INTEGER NOT NULL,
                    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
                    report_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS geography_block_groups (
                    source_id TEXT PRIMARY KEY,
                    municipality TEXT NOT NULL,
                    total_population INTEGER,
                    percent_minority REAL,
                    limited_english_household_percent REAL,
                    block_group_median_household_income_usd REAL,
                    ej_flag TEXT NOT NULL CHECK (ej_flag = 'Yes'),
                    ej_criteria_description TEXT,
                    percent_unit TEXT NOT NULL CHECK (percent_unit = 'percentage_points_0_to_100'),
                    population_unit TEXT NOT NULL CHECK (population_unit = 'persons'),
                    income_unit TEXT NOT NULL,
                    geometry_json TEXT CHECK (geometry_json IS NULL),
                    source_scope TEXT NOT NULL CHECK (source_scope = 'aggregate_community_block_group')
                );
                CREATE TABLE IF NOT EXISTS geography_municipalities (
                    municipality TEXT PRIMARY KEY,
                    source_scope TEXT NOT NULL,
                    aggregate_json TEXT NOT NULL
                );
                """
            )

    def save_acquisition_report(self, report: AcquisitionReport) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO geography_acquisition_runs (
                    started_at_utc, finished_at_utc, source_url, object_id_field,
                    expected_source_count, fetched_record_count, unique_accepted_count,
                    duplicate_count, invalid_quarantined_count, complete, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.started_at_utc.isoformat(), report.finished_at_utc.isoformat(),
                    report.source_url, report.object_id_field, report.expected_source_count,
                    report.fetched_record_count, report.unique_accepted_count,
                    report.duplicate_count, report.invalid_quarantined_count,
                    int(report.complete), report.model_dump_json(),
                ),
            )
            return int(cursor.lastrowid)

    def replace_block_groups(self, records: tuple[NormalizedBlockGroup, ...]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM geography_block_groups")
            connection.executemany(
                """INSERT INTO geography_block_groups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        r.source_id, r.municipality, r.total_population, r.percent_minority,
                        r.limited_english_household_percent,
                        r.block_group_median_household_income_usd, r.ej_flag,
                        r.ej_criteria_description, r.percent_unit, r.population_unit,
                        r.income_unit, None, r.source_scope,
                    )
                    for r in records
                ],
            )

    def replace_municipalities(self, records: tuple[MunicipalityEJSubsetAggregate, ...]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM geography_municipalities")
            connection.executemany(
                "INSERT INTO geography_municipalities VALUES (?, ?, ?)",
                [(r.municipality, r.source_scope, json.dumps(r.model_dump())) for r in records],
            )

    def cache_raw_records(self, result: IngestionResult, destination: str | Path) -> str:
        """Atomically cache required raw attributes and attach their SHA-256 to the report."""

        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                [record.model_dump() for record in result.records],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
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
        result.report.raw_snapshot_sha256 = checksum
        result.report.raw_snapshot_record_count = len(result.records)
        return checksum
