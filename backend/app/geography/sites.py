"""Clinical-site export adaptation without clinical-internal imports or geocoding."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import SiteAdapterReport, SiteAdapterResult, TrialSite

_MA = {"ma", "massachusetts"}


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def is_massachusetts_site(site: TrialSite) -> bool:
    state = re.sub(r"[^a-z]", "", _normalize(site.state))
    return state in _MA


def site_deduplication_key(site: TrialSite) -> tuple[str, ...]:
    if site.facility_source_id and site.facility_source_id.strip():
        return ("stable_source_id", _normalize(site.nct_id), _normalize(site.facility_source_id))
    return (
        "normalized_tuple", _normalize(site.nct_id), _normalize(site.facility_name),
        _normalize(site.city), _normalize(site.state), _normalize(site.postal_code),
        "" if site.latitude is None else f"{site.latitude:.8f}",
        "" if site.longitude is None else f"{site.longitude:.8f}",
    )


def is_recruiting_site(site: TrialSite) -> bool:
    """Fail closed: only an explicit recruiting status enters access analysis."""

    return _normalize(site.overall_status) == "recruiting"


def matches_condition(site: TrialSite, condition: str | None) -> bool:
    if condition is None:
        return True
    target = _normalize(condition)
    if not target:
        raise ValueError("condition filter must not be blank")
    return any(_normalize(value) == target for value in site.conditions)


def adapt_trial_sites(sites: Iterable[TrialSite], *, condition: str | None = None) -> SiteAdapterResult:
    input_sites = tuple(sites)
    in_state = [site for site in input_sites if is_massachusetts_site(site)]
    recruiting = [site for site in in_state if is_recruiting_site(site)]
    filtered = [site for site in recruiting if matches_condition(site, condition)]
    deduplicated: dict[tuple[str, ...], TrialSite] = {}
    for site in sorted(filtered, key=lambda s: (site_deduplication_key(s), _normalize(s.nct_id))):
        deduplicated.setdefault(site_deduplication_key(site), site)
    accepted = tuple(sorted(deduplicated.values(), key=lambda s: (_normalize(s.nct_id), _normalize(s.facility_name), site_deduplication_key(s))))
    resolved = sum(site.resolution_status in {"source_coordinates", "verified_geocode"} for site in accepted)
    report = SiteAdapterReport(
        input_count=len(input_sites), massachusetts_count=len(in_state),
        out_of_state_count=len(input_sites) - len(in_state),
        non_recruiting_or_unknown_count=len(in_state) - len(recruiting),
        deduplicated_count=len(accepted),
        duplicate_count=len(filtered) - len(accepted), resolved_count=resolved,
        unresolved_count=len(accepted) - resolved, condition_filter=condition,
        deduplication_method="stable facility_source_id first; otherwise normalized NCT/facility/city/state/postal/coordinate tuple",
    )
    return SiteAdapterResult(sites=accepted, report=report)


# The clinical workstream owns export production. This adapter deliberately accepts
# only the agreed exchange fields and never imports clinical implementation code.
import json
import math
import os
from pathlib import Path
from typing import Any

from pydantic import Field

from .models import StrictModel

DEFAULT_SITE_EXPORT_PATH = Path("backend/data/exports/ma_trial_sites.json")


class SiteExportReport(StrictModel):
    path: str
    available: bool
    input_count: int | None = Field(default=None, ge=0)
    accepted_count: int | None = Field(default=None, ge=0)
    quarantined_count: int | None = Field(default=None, ge=0)
    quarantine_reasons: tuple[str, ...] = ()


class SiteExportResult(StrictModel):
    sites: tuple[TrialSite, ...]
    report: SiteExportReport


def configured_site_export_path() -> Path:
    return Path(os.environ.get("TRIALMATCH_SITE_EXPORT_PATH", DEFAULT_SITE_EXPORT_PATH))


def _normalized_coordinate_status(value: Any, has_coordinates: bool) -> str:
    if value is None:
        return "source_coordinates" if has_coordinates else "unresolved"
    normalized = re.sub(r"[^a-z]+", "_", str(value).strip().casefold()).strip("_")
    aliases = {
        "source": "source_coordinates",
        "provided": "source_coordinates",
        "resolved": "source_coordinates",
        "source_coordinate": "source_coordinates",
        "source_coordinates": "source_coordinates",
        "geocoded": "verified_geocode",
        "verified_geocode": "verified_geocode",
        "verified_geocoded": "verified_geocode",
        "missing": "unresolved",
        "unknown": "unresolved",
        "unresolved": "unresolved",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported coordinate status {value!r}")
    return aliases[normalized]


def _normalized_recruiting_status(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")
    return normalized.upper() or None


def _export_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("records", "items", "sites"):
            if key in payload:
                records = payload[key]
                if not isinstance(records, list):
                    raise ValueError(f"clinical site export {key!r} must be an array")
                return records
    raise ValueError("clinical site export must be an array or records/items/sites envelope")


def _trial_site_from_export(record: Any, *, source_reference: str) -> TrialSite:
    if not isinstance(record, dict):
        raise ValueError("site record must be an object")
    latitude = record.get("latitude", record.get("lat"))
    longitude = record.get("longitude", record.get("lon"))
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be present together")
    has_coordinates = latitude is not None
    if has_coordinates:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            raise ValueError("coordinates must be finite numbers")
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError) as exc:
            raise ValueError("coordinates must be finite numbers") from exc
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("coordinates must be finite numbers")
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("coordinates are outside valid latitude/longitude ranges")
    status_value = record.get("resolution_status")
    if status_value is None:
        status_value = record.get("coordinate_status")
    status = _normalized_coordinate_status(status_value, has_coordinates)
    if has_coordinates != (status in {"source_coordinates", "verified_geocode"}):
        raise ValueError("coordinate status conflicts with coordinate availability")
    state = record.get("state")
    country = record.get("country")
    normalized_state = re.sub(r"[^a-z]", "", _normalize(state))
    normalized_country = re.sub(r"[^a-z]", "", _normalize(country))
    if normalized_state in _MA and normalized_country not in {
        "us", "usa", "unitedstates", "unitedstatesofamerica"
    }:
        raise ValueError("Massachusetts site must identify the country as United States")
    source_url = record.get("source_url")
    recruiting_status = record.get("overall_status")
    if recruiting_status is None:
        recruiting_status = record.get("recruiting_status")
    return TrialSite(
        nct_id=record.get("nct_id"),
        conditions=record.get("conditions", ()),
        facility_source_id=record.get("facility_source_id"),
        facility_name=record.get("facility_name"),
        city=record.get("city"),
        state=state,
        postal_code=record.get("postal_code"),
        country=country,
        latitude=latitude,
        longitude=longitude,
        coordinate_source=(
            record.get("coordinate_source")
            or ("clinical_export_source_coordinates" if status == "source_coordinates" else "clinical_export_verified_geocode")
            if has_coordinates
            else None
        ),
        coordinate_source_reference=(
            record.get("coordinate_source_reference") or source_url or source_reference
            if has_coordinates
            else None
        ),
        resolution_status=status,
        overall_status=_normalized_recruiting_status(recruiting_status),
        source_url=source_url,
        retrieved_at=record.get("retrieved_at"),
    )


def load_trial_site_export(path: str | Path | None = None) -> SiteExportResult:
    """Load and quarantine bad exchange rows; a missing file is unavailable, not empty."""

    source = Path(path) if path is not None else configured_site_export_path()
    if not source.is_file():
        return SiteExportResult(
            sites=(), report=SiteExportReport(path=str(source), available=False)
        )
    payload = json.loads(source.read_text(encoding="utf-8"))
    records = _export_records(payload)
    accepted: list[TrialSite] = []
    reasons: list[str] = []
    for index, record in enumerate(records):
        try:
            accepted.append(_trial_site_from_export(record, source_reference=str(source)))
        except (TypeError, ValueError) as exc:
            reasons.append(f"record {index}: {exc}")
    return SiteExportResult(
        sites=tuple(accepted),
        report=SiteExportReport(
            path=str(source),
            available=True,
            input_count=len(records),
            accepted_count=len(accepted),
            quarantined_count=len(reasons),
            quarantine_reasons=tuple(reasons),
        ),
    )
