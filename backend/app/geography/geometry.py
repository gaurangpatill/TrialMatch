"""Official MassGIS polygon acquisition and municipality analytical points."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import MassGISClient, MassGISClientError
from .models import (
    ArcGISFeature,
    BlockGroupRepresentativePoint,
    GeometryAcquisitionReport,
    MunicipalityPointSnapshot,
    MunicipalityRepresentativePoint,
)

GEOMETRY_FIELDS = ("MUNICIPALITY", "TOTAL_POP")
WHERE_EJ_YES = "EJ='Yes'"
DEFAULT_SNAPSHOT_PATH = Path(__file__).with_name("data") / "municipality_ej_representative_points.json"


def _point(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        longitude, latitude = float(value["x"]), float(value["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return latitude, longitude


def polygon_area_centroid(geometry: Any) -> tuple[float, float] | None:
    """Compute the signed-area centroid of official WGS84 polygon rings."""

    if not isinstance(geometry, dict) or not isinstance(geometry.get("rings"), list):
        return None
    area_twice = centroid_x = centroid_y = 0.0
    for ring in geometry["rings"]:
        if not isinstance(ring, list) or len(ring) < 4:
            return None
        parsed: list[tuple[float, float]] = []
        for coordinate in ring:
            if not isinstance(coordinate, list) or len(coordinate) < 2:
                return None
            try:
                x, y = float(coordinate[0]), float(coordinate[1])
            except (TypeError, ValueError):
                return None
            if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
                return None
            parsed.append((x, y))
        if parsed[0] != parsed[-1]:
            return None
        for (x1, y1), (x2, y2) in zip(parsed, parsed[1:]):
            cross = x1 * y2 - x2 * y1
            area_twice += cross
            centroid_x += (x1 + x2) * cross
            centroid_y += (y1 + y2) * cross
    if abs(area_twice) < 1e-15:
        return None
    longitude = centroid_x / (3.0 * area_twice)
    latitude = centroid_y / (3.0 * area_twice)
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return latitude, longitude


def representative_point(feature: ArcGISFeature, prefer_server_centroid: bool) -> tuple[tuple[float, float] | None, str | None]:
    if prefer_server_centroid:
        server = _point(feature.centroid)
        if server is not None:
            return server, "arcgis_returned_centroid"
    computed = polygon_area_centroid(feature.geometry)
    return (computed, "polygon_area_centroid") if computed is not None else (None, None)


def aggregate_representative_points(
    rows: list[tuple[str, str, int | None, tuple[float, float] | None, str]],
) -> tuple[MunicipalityRepresentativePoint, ...]:
    grouped: dict[str, list[tuple[str, int | None, tuple[float, float] | None, str]]] = defaultdict(list)
    for source_id, municipality, population, point, geometry_status in rows:
        grouped[municipality].append((source_id, population, point, geometry_status))
    output: list[MunicipalityRepresentativePoint] = []
    for municipality in sorted(grouped, key=lambda x: (x.casefold(), x)):
        group = grouped[municipality]
        valid = [(source_id, population, point) for source_id, population, point, _ in group if point]
        positive = [(population, point) for _, population, point in valid if population is not None and population > 0]
        if positive:
            denominator = sum(population for population, _ in positive)
            latitude = sum(population * point[0] for population, point in positive) / denominator
            longitude = sum(population * point[1] for population, point in positive) / denominator
            method = "population_weighted_mean_of_ej_block_group_points"
        elif valid:
            denominator = 0
            latitude = sum(point[0] for _, _, point in valid) / len(valid)
            longitude = sum(point[1] for _, _, point in valid) / len(valid)
            method = "unweighted_mean_fallback_zero_or_missing_population"
        else:
            denominator = 0
            latitude = longitude = None
            method = "unresolved_no_valid_geometry"
        output.append(MunicipalityRepresentativePoint(
            municipality=municipality, latitude=latitude, longitude=longitude,
            resolution_status="resolved" if valid else "unresolved", point_method=method,
            block_group_source_count=len(group), valid_geometry_count=len(valid),
            missing_geometry_count=sum(status == "missing" for _, _, _, status in group),
            invalid_geometry_count=sum(status == "invalid" for _, _, _, status in group),
            represented_population=denominator,
            source_ids=tuple(sorted(source_id for source_id, _, _, _ in group)),
        ))
    return tuple(output)


class MassGISGeometryService:
    def __init__(self, client: MassGISClient, *, page_size: int = 100) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.client = client
        self.page_size = page_size

    def acquire(self) -> MunicipalityPointSnapshot:
        metadata = self.client.get_metadata()
        oid = metadata.object_id_field
        if not oid:
            raise MassGISClientError("layer metadata does not identify an object ID field")
        expected = self.client.get_count(WHERE_EJ_YES)
        page_size = min(self.page_size, metadata.maxRecordCount or self.page_size)
        prefer_server = bool(metadata.advancedQueryCapabilities and metadata.advancedQueryCapabilities.supportsReturningGeometryCentroid)
        params: dict[str, str | int | bool] = {
            "f": "json", "where": WHERE_EJ_YES, "outFields": f"{oid},MUNICIPALITY,TOTAL_POP",
            "returnGeometry": "true", "outSR": 4326, "resultRecordCount": page_size,
            "orderByFields": f"{oid} ASC",
        }
        if prefer_server:
            params["returnCentroid"] = "true"
        rows: list[tuple[str, str, int | None, tuple[float, float] | None, str]] = []
        seen: set[str] = set()
        fingerprints: set[str] = set()
        duplicate_count = missing = invalid = source_invalid = arcgis_count = polygon_count = page_count = fetched = 0
        offset = 0
        complete = False
        while True:
            page = self.client.query_page({**params, "resultOffset": offset})
            page_count += 1
            canonical = json.dumps([f.model_dump() for f in page.features], sort_keys=True, default=str)
            fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
            if page.features and fingerprint in fingerprints:
                break
            fingerprints.add(fingerprint)
            for feature in page.features:
                fetched += 1
                attributes = feature.attributes
                source_id = str(attributes.get(oid, "")).strip()
                municipality = attributes.get("MUNICIPALITY")
                population = attributes.get("TOTAL_POP")
                if not source_id or not isinstance(municipality, str) or not municipality.strip() or isinstance(population, bool):
                    source_invalid += 1
                    continue
                if source_id in seen:
                    duplicate_count += 1
                    continue
                seen.add(source_id)
                if population is not None:
                    try:
                        population_number = float(population)
                    except (TypeError, ValueError):
                        source_invalid += 1
                        continue
                    if isinstance(population, bool) or not math.isfinite(population_number) or population_number < 0 or not population_number.is_integer():
                        source_invalid += 1
                        continue
                    population = int(population_number)
                point, method = representative_point(feature, prefer_server)
                if point is None:
                    geometry_status = "missing" if feature.geometry is None and feature.centroid is None else "invalid"
                    if geometry_status == "missing":
                        missing += 1
                    else:
                        invalid += 1
                elif method == "arcgis_returned_centroid":
                    geometry_status = "valid"
                    arcgis_count += 1
                else:
                    geometry_status = "valid"
                    polygon_count += 1
                rows.append((source_id, municipality.strip(), population, point, geometry_status))
            page_length = len(page.features)
            offset += page_length
            if page.exceededTransferLimit or fetched < expected:
                if page_length == 0:
                    break
                continue
            complete = fetched == expected and duplicate_count == 0 and source_invalid == 0
            break
        municipalities = list(aggregate_representative_points(rows))
        # Attribute invalid source rows globally; per-municipality invalid geometry is retained via null points.
        unresolved = sum(item.resolution_status == "unresolved" for item in municipalities)
        source_wkid = metadata.spatialReference.latestWkid if metadata.spatialReference and metadata.spatialReference.latestWkid else (metadata.spatialReference.wkid if metadata.spatialReference else None)
        report = GeometryAcquisitionReport(
            source_layer_url=self.client.layer_url,
            source_crs=f"EPSG:{source_wkid}" if source_wkid else "ArcGIS layer spatial reference (server metadata did not expose WKID)",
            server_transformation_method="ArcGIS outSR=4326 server projection",
            acquisition_utc=datetime.now(timezone.utc), object_id_field=oid,
            query_parameters=params, expected_source_count=expected, fetched_record_count=fetched,
            unique_source_count=len(seen), duplicate_count=duplicate_count, page_count=page_count,
            complete=complete, invalid_source_record_count=source_invalid,
            missing_geometry_count=missing, invalid_geometry_count=invalid,
            arcgis_centroid_count=arcgis_count, polygon_centroid_count=polygon_count,
            resolved_municipality_count=len(municipalities) - unresolved,
            unresolved_municipality_count=unresolved,
            limitations=("Representative analytical points are derived from EJ block groups; they are not venues or trial sites.", "Polygon centroids and weighted means may fall outside irregular boundaries.",),
        )
        return MunicipalityPointSnapshot(report=report, municipalities=tuple(municipalities))


def save_snapshot(snapshot: MunicipalityPointSnapshot, destination: str | Path = DEFAULT_SNAPSHOT_PATH) -> int:
    """Atomically persist canonical compact JSON and return byte size."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
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
    return len(payload)


def load_snapshot(source: str | Path = DEFAULT_SNAPSHOT_PATH) -> MunicipalityPointSnapshot:
    return MunicipalityPointSnapshot.model_validate_json(Path(source).read_text(encoding="utf-8"))


def regenerate_official_snapshot(destination: str | Path = DEFAULT_SNAPSHOT_PATH, *, page_size: int = 500) -> MunicipalityPointSnapshot:
    """CLI-callable live regeneration without retaining raw polygons."""
    with MassGISClient() as client:
        snapshot = MassGISGeometryService(client, page_size=page_size).acquire()
    if not snapshot.report.complete:
        raise MassGISClientError("geometry acquisition did not reconcile completely; snapshot not replaced")
    save_snapshot(snapshot, destination)
    return snapshot
