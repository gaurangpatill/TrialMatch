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
