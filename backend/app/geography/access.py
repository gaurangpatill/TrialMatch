"""Transparent municipality-to-resolved-trial-site access indicators."""

from __future__ import annotations

from collections.abc import Iterable

from backend.app.optimizer import haversine_km

from .models import AccessIndicator, MunicipalityRepresentativePoint, TrialSite
from .sites import adapt_trial_sites


def compute_access_indicators(
    municipalities: Iterable[MunicipalityRepresentativePoint],
    sites: Iterable[TrialSite], *, radius_km: float, condition: str | None = None,
) -> tuple[AccessIndicator, ...]:
    if radius_km < 0:
        raise ValueError("radius_km must be nonnegative")
    adapted = adapt_trial_sites(sites, condition=condition)
    resolved = tuple(site for site in adapted.sites if site.resolution_status in {"source_coordinates", "verified_geocode"})
    output: list[AccessIndicator] = []
    for municipality in sorted(municipalities, key=lambda x: (x.municipality.casefold(), x.municipality)):
        distances: list[tuple[float, str]] = []
        if municipality.resolution_status == "resolved":
            for site in resolved:
                assert municipality.latitude is not None and municipality.longitude is not None
                assert site.latitude is not None and site.longitude is not None
                distances.append((haversine_km(municipality.latitude, municipality.longitude, site.latitude, site.longitude), site.nct_id.upper()))
        output.append(AccessIndicator(
            municipality=municipality.municipality,
            municipality_resolution_status=municipality.resolution_status,
            spatial_analysis_available=municipality.resolution_status == "resolved",
            nearest_resolved_recruiting_site_distance_km=min((distance for distance, _ in distances), default=None),
            distinct_nearby_nct_count=len({nct for distance, nct in distances if distance <= radius_km + 1e-9}),
            inclusive_radius_km=radius_km, condition_filter=condition,
            total_site_count=adapted.report.input_count, resolved_site_count=adapted.report.resolved_count,
            unresolved_site_count=adapted.report.unresolved_count,
            deduplicated_site_count=adapted.report.deduplicated_count,
        ))
    return tuple(output)
