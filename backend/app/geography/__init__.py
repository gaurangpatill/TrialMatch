"""Geographic intelligence source acquisition and aggregate analysis."""

from .client import OFFICIAL_EJ_LAYER_URL, MassGISClient, MassGISClientError
from .geometry import (
    DEFAULT_SNAPSHOT_PATH,
    MassGISGeometryService,
    load_snapshot,
    regenerate_official_snapshot,
    save_snapshot,
)
from .ingestion import GeographyIngestionService
from .access import compute_access_indicators
from .scenario import build_real_ej_scenario
from .sites import adapt_trial_sites
from .transform import aggregate_municipalities, normalize_record, normalize_records

__all__ = [
    "DEFAULT_SNAPSHOT_PATH",
    "OFFICIAL_EJ_LAYER_URL",
    "GeographyIngestionService",
    "MassGISClient",
    "MassGISClientError",
    "MassGISGeometryService",
    "adapt_trial_sites",
    "aggregate_municipalities",
    "build_real_ej_scenario",
    "compute_access_indicators",
    "load_snapshot",
    "normalize_record",
    "normalize_records",
    "regenerate_official_snapshot",
    "save_snapshot",
]
