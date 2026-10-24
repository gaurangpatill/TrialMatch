"use client";

import {useEffect, useMemo, useRef, useState} from "react";
import * as maplibregl from "maplibre-gl";
import type {GeoJSONSource, Map as MapLibreMap} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import type {GeoCollection, GeoFeature, RecruitingSiteFeature, SelectedLocation} from "./types";
import styles from "./researcher.module.css";

const MUNICIPALITY_SOURCE = "municipalities";
const SITE_SOURCE = "recruiting-sites";
const CATCHMENT_SOURCE = "outreach-catchments";
const CATCHMENT_FILL = "catchment-fill";
const CATCHMENT_LINE = "catchment-line";
const UNCOVERED_LAYER = "uncovered-communities";
const COVERED_LAYER = "covered-communities";
const SITE_CLUSTER_LAYER = "site-clusters";
const SITE_CLUSTER_COUNT_LAYER = "site-cluster-count";
const SITE_LAYER = "recruiting-site-symbols";
const SITE_LABEL_LAYER = "recruiting-site-label";
const SELECTED_RING_LAYER = "selected-outreach-rings";
const SELECTED_LABEL_LAYER = "selected-outreach-labels";
const MA_BOUNDS: maplibregl.LngLatBoundsLike = [[-73.6, 41.15], [-69.75, 43.05]];
const EARTH_RADIUS_KM = 6371.0088;

type VisualizationMode = "access" | "planning";
type MapStatus = "initializing" | "ready" | "error";

function municipalityData(
  data: GeoCollection,
  selectedLocations: SelectedLocation[],
  coveredIds: Set<string>,
  mode: VisualizationMode,
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  const order = new Map(selectedLocations.map((location, index) => [location.municipality_id, index + 1]));
  return {
    type: "FeatureCollection",
    features: data.features.flatMap((feature) => feature.geometry ? [{
      type: "Feature" as const,
      id: feature.id,
      geometry: feature.geometry,
      properties: {
        ...feature.properties,
        selected: order.has(feature.id) ? 1 : 0,
        selection_order: order.get(feature.id) ?? 0,
        covered: coveredIds.has(feature.id) ? 1 : 0,
        mode_planning: mode === "planning" ? 1 : 0,
        population: feature.properties.ej_subset_population ?? 0,
        access_available: feature.properties.distinct_nearby_recruiting_nct_count === null ? 0 : 1,
        nearby_nct_count: feature.properties.distinct_nearby_recruiting_nct_count ?? -1,
      },
    }] : []),
  };
}

function siteData(data: GeoCollection): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: "FeatureCollection",
    features: data.recruiting_site_features.flatMap((feature) => feature.geometry ? [{
      type: "Feature" as const,
      id: feature.id,
      geometry: feature.geometry,
      properties: {
        id: feature.id,
        nct_id: feature.properties.nct_id,
        facility: feature.properties.facility,
      },
    }] : []),
  };
}

function destinationPoint(longitude: number, latitude: number, distanceKm: number, bearingRadians: number): [number, number] {
  const angularDistance = distanceKm / EARTH_RADIUS_KM;
  const latitudeRadians = latitude * Math.PI / 180;
  const longitudeRadians = longitude * Math.PI / 180;
  const destinationLatitude = Math.asin(
    Math.sin(latitudeRadians) * Math.cos(angularDistance)
    + Math.cos(latitudeRadians) * Math.sin(angularDistance) * Math.cos(bearingRadians),
  );
  const destinationLongitude = longitudeRadians + Math.atan2(
    Math.sin(bearingRadians) * Math.sin(angularDistance) * Math.cos(latitudeRadians),
    Math.cos(angularDistance) - Math.sin(latitudeRadians) * Math.sin(destinationLatitude),
  );
  const normalizedLongitude = ((destinationLongitude * 180 / Math.PI + 540) % 360) - 180;
  return [normalizedLongitude, destinationLatitude * 180 / Math.PI];
}

function catchmentData(selectedLocations: SelectedLocation[], radiusKm: number | null): GeoJSON.FeatureCollection<GeoJSON.Polygon> {
  if (radiusKm === null || radiusKm <= 0) return {type: "FeatureCollection", features: []};
  return {
    type: "FeatureCollection",
    features: selectedLocations.map((location, index) => {
      const ring = Array.from({length: 65}, (_, pointIndex) => destinationPoint(
        location.longitude,
        location.latitude,
        radiusKm,
        (Math.PI * 2 * (pointIndex % 64)) / 64,
      ));
      return {
        type: "Feature" as const,
        id: `catchment-${location.municipality_id}`,
        geometry: {type: "Polygon" as const, coordinates: [ring]},
        properties: {municipality: location.municipality_id, selection_order: index + 1, radius_km: radiusKm},
      };
    }),
  };
}

function createLabelImage(label: string, color: string): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = 48;
  canvas.height = 48;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas labels are unavailable in this browser.");
  context.clearRect(0, 0, 48, 48);
  context.fillStyle = color;
  context.font = "800 22px system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, 24, 25, 44);
  return context.getImageData(0, 0, 48, 48);
}

function addLocalLabelImages(map: MapLibreMap, maximumClusterCount: number) {
  if (!map.hasImage("site-plus")) map.addImage("site-plus", createLabelImage("+", "#ffffff"), {pixelRatio: 2});
  for (let value = 1; value <= Math.max(20, maximumClusterCount); value += 1) {
    const clusterName = `cluster-count-${value}`;
    if (!map.hasImage(clusterName)) map.addImage(clusterName, createLabelImage(String(value), "#ffffff"), {pixelRatio: 2});
    if (value <= 20) {
      const selectionName = `selection-label-${value}`;
      if (!map.hasImage(selectionName)) map.addImage(selectionName, createLabelImage(String(value), "#3e2604"), {pixelRatio: 2});
    }
  }
}

function text(value: string | number | null | undefined, fallback = "Unavailable") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function popupBody(title: string, rows: Array<[string, string]>, warning?: string, sourceUrl?: string | null) {
  const root = document.createElement("div");
  root.className = styles.popupBody;
  const heading = document.createElement("strong");
  heading.textContent = title;
  root.appendChild(heading);
  for (const [label, value] of rows) {
    const row = document.createElement("span");
    const labelNode = document.createElement("b");
    labelNode.textContent = `${label}: `;
    row.append(labelNode, document.createTextNode(value));
    root.appendChild(row);
  }
  if (sourceUrl) {
    try {
      const url = new URL(sourceUrl);
      if (url.protocol === "https:" || url.protocol === "http:") {
        const link = document.createElement("a");
        link.href = url.toString();
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = "Open study source";
        root.appendChild(link);
      }
    } catch {
      // Invalid source URLs are omitted rather than inserted into the DOM.
    }
  }
  if (warning) {
    const note = document.createElement("small");
    note.textContent = warning;
    root.appendChild(note);
  }
  return root;
}

function municipalityPopup(feature: GeoFeature) {
  const properties = feature.properties;
  const nearby = properties.distinct_nearby_recruiting_nct_count;
  const nearest = properties.nearest_resolved_recruiting_site_distance_km;
  return popupBody(feature.id, [
    ["EJ-subset population", properties.ej_subset_population === null ? "Unavailable" : properties.ej_subset_population.toLocaleString()],
    ["Weighted minority share", properties.population_weighted_percent_minority_ej_subset === null ? "Unavailable" : `${properties.population_weighted_percent_minority_ej_subset.toFixed(1)}%`],
    ["Limited-English households", properties.population_weighted_limited_english_household_percent_ej_subset === null ? "Unavailable" : `${properties.population_weighted_limited_english_household_percent_ej_subset.toFixed(1)}%`],
    ["Nearby distinct NCTs", nearby === null ? "Unavailable (clinical export not loaded)" : nearby === 0 ? "0 — no matching NCTs within radius" : nearby.toLocaleString()],
    ["Nearest matching trial", nearest === null ? (nearby === null ? "Unavailable" : "No resolved matching site") : `${nearest.toFixed(1)} km`],
  ], properties.access_distance_limitation ?? "Representative analytical point — not a boundary, venue, or patient location.");
}

function sitePopup(feature: RecruitingSiteFeature) {
  const properties = feature.properties;
  const locality = [properties.city, properties.state, properties.postal_code, properties.country].filter(Boolean).join(", ");
  return popupBody(properties.facility, [
    ["NCT ID", properties.nct_id],
    ["Location", locality || "Unavailable"],
    ["Recruiting status", text(properties.recruiting_status)],
    ["Conditions", properties.conditions.length ? properties.conditions.join("; ") : "Unavailable"],
    ["Coordinate status", properties.coordinate_resolution_status],
    ["Coordinate source", text(properties.coordinate_source)],
    ["Source reference", text(properties.coordinate_source_reference)],
    ["Retrieved", properties.retrieved_at ? new Date(properties.retrieved_at).toLocaleDateString("en-US") : "Unavailable"],
  ], properties.coordinate_approximation_warning, properties.source_url);
}

export default function ResearcherMap({data, selectedLocations, coveredIds, submittedRadiusKm, visualizationMode, onSelect}: {
  data: GeoCollection;
  selectedLocations: SelectedLocation[];
  coveredIds: Set<string>;
  submittedRadiusKm: number | null;
  visualizationMode: VisualizationMode;
  onSelect: (feature: GeoFeature) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const propsRef = useRef({data, selectedLocations, coveredIds, submittedRadiusKm, visualizationMode, onSelect});
  const [mapStatus, setMapStatus] = useState<MapStatus>("initializing");
  const [mapError, setMapError] = useState<string | null>(null);
  propsRef.current = {data, selectedLocations, coveredIds, submittedRadiusKm, visualizationMode, onSelect};

  const resolvedMunicipalityCount = useMemo(() => data.features.filter((feature) => feature.geometry).length, [data]);
  const resolvedSiteCount = useMemo(() => data.recruiting_site_features.filter((feature) => feature.geometry).length, [data]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let map: MapLibreMap;
    try {
      maplibregl.setWorkerUrl(new URL("/maplibre-gl-worker.mjs", window.location.origin).toString());
      map = new maplibregl.Map({
        container: containerRef.current,
        bounds: MA_BOUNDS,
        fitBoundsOptions: {padding: 24},
        attributionControl: false,
        style: {
          version: 8,
          sources: {
            osm: {type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors"},
          },
          layers: [{id: "osm", type: "raster", source: "osm", paint: {"raster-saturation": -0.75, "raster-opacity": 0.86}}],
        },
      });
    } catch (error) {
      setMapStatus("error");
      setMapError(error instanceof Error ? error.message : "MapLibre could not initialize WebGL.");
      return;
    }
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-right");
    map.addControl(new maplibregl.AttributionControl({compact: true}), "bottom-right");

    map.on("error", (event) => {
      if (mapRef.current !== map) return;
      const message = event.error?.message || "MapLibre reported an unknown rendering error.";
      if (/worker|webgl|gpu|context|style/i.test(message)) {
        setMapStatus("error");
        setMapError(message);
      } else {
        console.warn("Nonfatal map resource error:", message);
      }
    });

    map.on("load", () => {
      if (mapRef.current !== map) return;
      const current = propsRef.current;
      addLocalLabelImages(map, current.data.recruiting_site_features.length);
      map.addSource(CATCHMENT_SOURCE, {type: "geojson", data: catchmentData(current.selectedLocations, current.submittedRadiusKm)});
      map.addSource(MUNICIPALITY_SOURCE, {type: "geojson", data: municipalityData(current.data, current.selectedLocations, current.coveredIds, current.visualizationMode)});
      map.addSource(SITE_SOURCE, {type: "geojson", data: siteData(current.data), cluster: true, clusterMaxZoom: 13, clusterRadius: 42});

      map.addLayer({id: CATCHMENT_FILL, type: "fill", source: CATCHMENT_SOURCE, paint: {"fill-color": "#d99a27", "fill-opacity": 0.12}});
      map.addLayer({id: CATCHMENT_LINE, type: "line", source: CATCHMENT_SOURCE, paint: {"line-color": "#9b6410", "line-width": 1.5, "line-dasharray": [3, 2]}});
      map.addLayer({
        id: UNCOVERED_LAYER,
        type: "circle",
        source: MUNICIPALITY_SOURCE,
        filter: ["all", ["==", ["get", "selected"], 0], ["any", ["==", ["get", "mode_planning"], 0], ["==", ["get", "covered"], 0]]],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "population"], 0, 5, 10000, 7, 75000, 12],
          "circle-color": ["case",
            ["==", ["get", "mode_planning"], 1], "#e6ecea",
            ["==", ["get", "access_available"], 0], "#d7dddb",
            ["==", ["get", "nearby_nct_count"], 0], "#f3f5f4",
            ["interpolate", ["linear"], ["get", "nearby_nct_count"], 1, "#b8c7ef", 3, "#6d83d7", 8, "#323783", 20, "#201a58"],
          ],
          "circle-opacity": 0.94,
          "circle-stroke-width": ["case", ["==", ["get", "nearby_nct_count"], 0], 2, 1.4],
          "circle-stroke-color": ["case", ["==", ["get", "mode_planning"], 1], "#657a75", ["==", ["get", "access_available"], 0], "#74837f", ["==", ["get", "nearby_nct_count"], 0], "#7a8985", "#ffffff"],
        },
      });
      map.addLayer({
        id: COVERED_LAYER,
        type: "circle",
        source: MUNICIPALITY_SOURCE,
        filter: ["all", ["==", ["get", "mode_planning"], 1], ["==", ["get", "covered"], 1], ["==", ["get", "selected"], 0]],
        paint: {"circle-radius": ["interpolate", ["linear"], ["get", "population"], 0, 5, 10000, 7, 75000, 12], "circle-color": "#16978b", "circle-opacity": 0.9, "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff"},
      });
      map.addLayer({id: SITE_CLUSTER_LAYER, type: "circle", source: SITE_SOURCE, filter: ["has", "point_count"], paint: {"circle-color": "#5856a6", "circle-radius": ["step", ["get", "point_count"], 15, 10, 19, 30, 24], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2, "circle-opacity": 0.92}});
      map.addLayer({id: SITE_CLUSTER_COUNT_LAYER, type: "symbol", source: SITE_SOURCE, filter: ["has", "point_count"], layout: {"icon-image": ["concat", "cluster-count-", ["to-string", ["get", "point_count"]]], "icon-size": 1, "icon-allow-overlap": true}});
      map.addLayer({id: SITE_LAYER, type: "circle", source: SITE_SOURCE, filter: ["!", ["has", "point_count"]], paint: {"circle-radius": 7, "circle-color": "#625bc2", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2}});
      map.addLayer({id: SITE_LABEL_LAYER, type: "symbol", source: SITE_SOURCE, filter: ["!", ["has", "point_count"]], layout: {"icon-image": "site-plus", "icon-size": 1, "icon-allow-overlap": true}});
      map.addLayer({id: SELECTED_RING_LAYER, type: "circle", source: MUNICIPALITY_SOURCE, filter: ["==", ["get", "selected"], 1], paint: {"circle-radius": 14, "circle-color": "#f5bd4f", "circle-stroke-color": "#633d06", "circle-stroke-width": 4}});
      map.addLayer({id: SELECTED_LABEL_LAYER, type: "symbol", source: MUNICIPALITY_SOURCE, filter: ["==", ["get", "selected"], 1], layout: {"icon-image": ["concat", "selection-label-", ["to-string", ["get", "selection_order"]]], "icon-size": 1, "icon-allow-overlap": true}});

      const handleMunicipalityClick = (event: maplibregl.MapLayerMouseEvent) => {
        const mapFeature = event.features?.[0];
        const id = String(mapFeature?.id ?? mapFeature?.properties?.municipality ?? "");
        const feature = propsRef.current.data.features.find((item) => item.id === id);
        if (!feature?.geometry) return;
        propsRef.current.onSelect(feature);
        new maplibregl.Popup({offset: 14, closeButton: true}).setLngLat(feature.geometry.coordinates).setDOMContent(municipalityPopup(feature)).addTo(map);
      };
      [UNCOVERED_LAYER, COVERED_LAYER, SELECTED_RING_LAYER, SELECTED_LABEL_LAYER].forEach((layer) => {
        map.on("click", layer, handleMunicipalityClick);
        map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
      });

      const handleSiteClick = (event: maplibregl.MapLayerMouseEvent) => {
        const mapFeature = event.features?.[0];
        const id = String(mapFeature?.id ?? mapFeature?.properties?.id ?? "");
        const feature = propsRef.current.data.recruiting_site_features.find((item) => item.id === id);
        if (!feature?.geometry) return;
        new maplibregl.Popup({offset: 12, closeButton: true}).setLngLat(feature.geometry.coordinates).setDOMContent(sitePopup(feature)).addTo(map);
      };
      [SITE_LAYER, SITE_LABEL_LAYER].forEach((layer) => {
        map.on("click", layer, handleSiteClick);
        map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
      });
      map.on("click", SITE_CLUSTER_LAYER, (event) => {
        const cluster = map.queryRenderedFeatures(event.point, {layers: [SITE_CLUSTER_LAYER]})[0];
        const clusterId = Number(cluster?.properties?.cluster_id);
        if (!Number.isFinite(clusterId) || cluster?.geometry.type !== "Point") return;
        const clusterCoordinates = cluster.geometry.coordinates as [number, number];
        const source = map.getSource(SITE_SOURCE) as GeoJSONSource;
        void source.getClusterExpansionZoom(clusterId).then((zoom) => map.easeTo({center: clusterCoordinates, zoom})).catch((error: unknown) => {
          setMapStatus("error");
          setMapError(error instanceof Error ? error.message : "Unable to expand the recruiting-site cluster.");
        });
      });
      map.on("mouseenter", SITE_CLUSTER_LAYER, () => { map.getCanvas().style.cursor = "zoom-in"; });
      map.on("mouseleave", SITE_CLUSTER_LAYER, () => { map.getCanvas().style.cursor = ""; });
      setMapStatus("ready");
      setMapError(null);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    (map.getSource(MUNICIPALITY_SOURCE) as GeoJSONSource | undefined)?.setData(municipalityData(data, selectedLocations, coveredIds, visualizationMode));
    (map.getSource(SITE_SOURCE) as GeoJSONSource | undefined)?.setData(siteData(data));
    (map.getSource(CATCHMENT_SOURCE) as GeoJSONSource | undefined)?.setData(catchmentData(selectedLocations, submittedRadiusKm));
  }, [coveredIds, data, selectedLocations, submittedRadiusKm, visualizationMode]);

  return (
    <div className={styles.mapFrame}>
      <div
        ref={containerRef}
        className={styles.map}
        role="region"
        aria-label="Massachusetts environmental-justice communities, recruiting sites, and outreach plan map"
        data-map-status={mapStatus}
        data-municipality-count={resolvedMunicipalityCount}
        data-site-count={resolvedSiteCount}
        data-selected-count={selectedLocations.length}
        data-covered-count={coveredIds.size}
      />
      <div className={`${styles.mapStatus} ${mapStatus === "error" ? styles.mapStatusError : ""}`} role={mapStatus === "error" ? "alert" : "status"}>
        {mapStatus === "initializing" ? "Initializing map…" : mapStatus === "ready" ? "Map loaded" : `Map error: ${mapError ?? "Unknown rendering failure"}`}
      </div>
    </div>
  );
}
