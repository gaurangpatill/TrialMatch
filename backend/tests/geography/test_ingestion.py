from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from backend.app.geography.client import MassGISClient, MassGISClientError
from backend.app.geography.ingestion import GeographyIngestionService
from backend.app.geography.models import (
    ArcGISAdvancedQueryCapabilities,
    ArcGISFeature,
    ArcGISField,
    ArcGISLayerMetadata,
    ArcGISQueryEnvelope,
)
from backend.app.geography.transform import REQUIRED_ATTRIBUTES


def attributes(object_id: int, **changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "OBJECTID": object_id,
        "MUNICIPALITY": "Boston",
        "TOTAL_POP": 100,
        "PCT_MINORITY": 20.0,
        "LIMENGHHPCT": 10.0,
        "BG_MHHI": 50_000.0,
        "EJ": "Yes",
        "EJ_CRIT_DESC": "Minority",
    }
    values.update(changes)
    return values


class FakeClient:
    layer_url = "https://example.test/MapServer/0"

    def __init__(self, pages: list[ArcGISQueryEnvelope], count: int, retry_count: int = 0) -> None:
        names = [*REQUIRED_ATTRIBUTES, "OBJECTID"]
        self.metadata = ArcGISLayerMetadata(
            objectIdField="OBJECTID", maxRecordCount=2,
            fields=[ArcGISField(name=name, type="esriFieldTypeString") for name in names],
            advancedQueryCapabilities=ArcGISAdvancedQueryCapabilities(supportsOrderBy=True),
        )
        self.pages = pages
        self.count = count
        self.retry_count = retry_count
        self.params: list[Mapping[str, Any]] = []

    def get_metadata(self) -> ArcGISLayerMetadata:
        return self.metadata

    def get_count(self, where: str) -> int:
        assert where == "EJ='Yes'"
        return self.count

    def query_page(self, params: Mapping[str, Any]) -> ArcGISQueryEnvelope:
        self.params.append(params)
        index = len(self.params) - 1
        if index >= len(self.pages):
            return ArcGISQueryEnvelope(features=[])
        return self.pages[index]


def page(*rows: dict[str, object], exceeded: bool = False) -> ArcGISQueryEnvelope:
    return ArcGISQueryEnvelope(
        features=[ArcGISFeature(attributes=row) for row in rows],
        exceededTransferLimit=exceeded,
    )


def test_multipage_pagination_uses_offsets_ordering_and_transfer_evidence() -> None:
    client = FakeClient(
        [page(attributes(1), attributes(2), exceeded=True), page(attributes(3))], count=3
    )
    result = GeographyIngestionService(client, page_size=10).acquire()  # type: ignore[arg-type]
    assert [record.source_id for record in result.records] == ["1", "2", "3"]
    assert [params["resultOffset"] for params in client.params] == [0, 2]
    assert client.params[0]["resultRecordCount"] == 2
    assert client.params[0]["orderByFields"] == "OBJECTID ASC"
    assert result.report.complete is True
    assert result.report.page_count == 2


def test_short_page_does_not_stop_when_transfer_limit_is_true() -> None:
    client = FakeClient([page(attributes(1), exceeded=True), page(attributes(2))], count=2)
    result = GeographyIngestionService(client, page_size=2).acquire()  # type: ignore[arg-type]
    assert result.report.complete
    assert len(client.params) == 2


def test_duplicates_are_detected_excluded_and_make_run_incomplete() -> None:
    client = FakeClient([page(attributes(1), attributes(1))], count=2)
    result = GeographyIngestionService(client, page_size=2).acquire()  # type: ignore[arg-type]
    assert len(result.records) == 1
    assert result.report.duplicate_count == 1
    assert result.report.duplicate_source_ids == ("1",)
    assert result.report.complete is False


def test_repeated_page_fingerprint_stops_loop() -> None:
    repeated = page(attributes(1), attributes(2), exceeded=True)
    client = FakeClient([repeated, repeated], count=4)
    result = GeographyIngestionService(client, page_size=2).acquire()  # type: ignore[arg-type]
    assert result.report.complete is False
    assert result.report.page_count == 2
    assert "repeated page" in result.report.termination_reason
    assert result.report.fetched_record_count == 2


def test_malformed_and_missing_fields_are_quarantined_with_reasons() -> None:
    missing = attributes(2)
    del missing["TOTAL_POP"]
    client = FakeClient([page(attributes(1, PCT_MINORITY="bad"), missing)], count=2)
    result = GeographyIngestionService(client, page_size=2).acquire()  # type: ignore[arg-type]
    assert result.records == ()
    assert result.report.invalid_quarantined_count == 2
    assert result.report.fetched_record_count == 2
    assert result.report.complete is False
    reasons = " ".join(item.reason for item in result.report.quarantined)
    assert "PCT_MINORITY" in reasons
    assert "missing required source field" in reasons


def test_count_mismatch_and_empty_page_mark_incomplete() -> None:
    client = FakeClient([page(attributes(1), attributes(2)), page()], count=3)
    result = GeographyIngestionService(client, page_size=2).acquire()  # type: ignore[arg-type]
    assert result.report.expected_source_count == 3
    assert result.report.fetched_record_count == 2
    assert result.report.complete is False
    assert "empty page" in result.report.termination_reason


def test_http_client_retries_transient_failure_then_validates_response() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request, json={"count": 7})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = MassGISClient(
        layer_url="https://example.test/0", http_client=http, max_attempts=2,
        backoff_seconds=0, sleeper=lambda _: None,
    )
    assert client.get_count("EJ='Yes'") == 7
    assert client.retry_count == 1
    assert attempts == 2


def test_http_client_has_finite_retries_and_rejects_bad_envelope() -> None:
    attempts = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=request)

    client = MassGISClient(
        layer_url="https://example.test/0",
        http_client=httpx.Client(transport=httpx.MockTransport(unavailable)),
        max_attempts=3, backoff_seconds=0, sleeper=lambda _: None,
    )
    with pytest.raises(MassGISClientError, match="after 3 attempt"):
        client.get_count("EJ='Yes'")
    assert attempts == 3
    assert client.retry_count == 2

    malformed = MassGISClient(
        layer_url="https://example.test/0",
        http_client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, request=request, json={"unexpected": []})
        )),
        max_attempts=1,
    )
    with pytest.raises(MassGISClientError, match="count envelope"):
        malformed.get_count("EJ='Yes'")


def test_object_id_is_discovered_from_oid_typed_field() -> None:
    metadata = ArcGISLayerMetadata(
        fields=[ArcGISField(name="OBJECTID", type="esriFieldTypeOID")]
    )
    assert metadata.object_id_field == "OBJECTID"


def test_present_null_source_values_are_preserved_and_counted() -> None:
    client = FakeClient(
        [page(attributes(1, TOTAL_POP=None, PCT_MINORITY=None, BG_MHHI=None))], count=1
    )
    result = GeographyIngestionService(client, page_size=2).acquire()  # type: ignore[arg-type]
    assert result.report.complete is True
    assert result.records[0].TOTAL_POP is None
    assert result.report.missing_value_counts["TOTAL_POP"] == 1
    assert result.report.missing_value_counts["PCT_MINORITY"] == 1
    assert result.report.missing_value_counts["BG_MHHI"] == 1
    assert result.report.schema_validated is True
