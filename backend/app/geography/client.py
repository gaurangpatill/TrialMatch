"""Mock-testable HTTP client for the official MassGIS ArcGIS layer."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from .models import ArcGISCountEnvelope, ArcGISError, ArcGISLayerMetadata, ArcGISQueryEnvelope

OFFICIAL_EJ_LAYER_URL = "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/EJ2020/MapServer/0"
TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class MassGISClientError(RuntimeError):
    """Raised when a bounded source request cannot yield a valid response."""


class MassGISClient:
    def __init__(
        self,
        *,
        layer_url: str = OFFICIAL_EJ_LAYER_URL,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.layer_url = layer_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._sleep = sleeper
        self.retry_count = 0

    def __enter__(self) -> "MassGISClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def _get_json(self, url: str, params: Mapping[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http.get(url, params=params, timeout=self.timeout_seconds)
                if response.status_code in TRANSIENT_STATUS_CODES:
                    raise httpx.HTTPStatusError(
                        f"transient MassGIS status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise MassGISClientError("ArcGIS response must be a JSON object")
                if "error" in payload:
                    try:
                        error = ArcGISError.model_validate(payload["error"])
                        detail = f"ArcGIS error {error.code}: {error.message}; {'; '.join(error.details)}"
                    except ValidationError:
                        detail = f"malformed ArcGIS error envelope: {payload['error']!r}"
                    raise MassGISClientError(detail)
                return payload
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                is_transient = isinstance(exc, httpx.TransportError) or (
                    exc.response is not None and exc.response.status_code in TRANSIENT_STATUS_CODES
                )
                if not is_transient or attempt == self.max_attempts:
                    break
                self.retry_count += 1
                self._sleep(self.backoff_seconds * (2 ** (attempt - 1)))
            except ValueError as exc:
                raise MassGISClientError(f"MassGIS returned invalid JSON: {exc}") from exc
        raise MassGISClientError(
            f"MassGIS request failed after {self.max_attempts} attempt(s): {last_error}"
        ) from last_error

    def get_metadata(self) -> ArcGISLayerMetadata:
        try:
            return ArcGISLayerMetadata.model_validate(self._get_json(self.layer_url, {"f": "json"}))
        except ValidationError as exc:
            raise MassGISClientError(f"invalid ArcGIS layer metadata: {exc}") from exc

    def get_count(self, where: str) -> int:
        params = {"f": "json", "where": where, "returnCountOnly": "true"}
        try:
            return ArcGISCountEnvelope.model_validate(
                self._get_json(f"{self.layer_url}/query", params)
            ).count
        except ValidationError as exc:
            raise MassGISClientError(f"invalid ArcGIS count envelope: {exc}") from exc

    def query_page(self, params: Mapping[str, Any]) -> ArcGISQueryEnvelope:
        try:
            return ArcGISQueryEnvelope.model_validate(
                self._get_json(f"{self.layer_url}/query", params)
            )
        except ValidationError as exc:
            raise MassGISClientError(f"invalid ArcGIS query envelope: {exc}") from exc
