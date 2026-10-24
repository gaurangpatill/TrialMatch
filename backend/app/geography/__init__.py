"""Geographic intelligence source acquisition and aggregate analysis."""

from .client import OFFICIAL_EJ_LAYER_URL, MassGISClient, MassGISClientError
from .ingestion import GeographyIngestionService
from .transform import aggregate_municipalities, normalize_record, normalize_records

__all__ = [
    "OFFICIAL_EJ_LAYER_URL",
    "GeographyIngestionService",
    "MassGISClient",
    "MassGISClientError",
    "aggregate_municipalities",
    "normalize_record",
    "normalize_records",
]
