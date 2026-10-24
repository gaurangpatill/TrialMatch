"use client";

import {useEffect, useRef} from "react";
import * as maplibregl from "maplibre-gl";
import type {GeoJSONSource, Map as MapLibreMap} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import type {GeoCollection, GeoFeature} from "./types";
import styles from "./researcher.module.css";

const SOURCE_ID = "municipalities";
const POINT_LAYER = "municipality-points";
const SELECTED_LAYER = "selected-municipalities";

function asMapData(data: GeoCollection, selectedIds: Set<string>): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: "FeatureCollection",
    features: data.features.flatMap((feature) => feature.geometry ? [{
      type: "Feature" as const,
      id: feature.id,
      geometry: feature.geometry,
      properties: {
        ...feature.properties,
        selected: selectedIds.has(feature.id) ? 1 : 0,
        population: feature.properties.ej_subset_population ?? 0,
        equity: feature.properties.population_weighted_percent_minority_ej_subset ?? 0,
      },
    }] : []),
  };
}

function escapeText(value: string) {
  return value.replace(/[&<>'"]/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"})[character] ?? character);
}

export default function ResearcherMap({data, selectedIds, onSelect}: {
  data: GeoCollection;
  selectedIds: Set<string>;
  onSelect: (feature: GeoFeature) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const dataRef = useRef(data);
  const selectedRef = useRef(selectedIds);
  const onSelectRef = useRef(onSelect);
  dataRef.current = data;
  selectedRef.current = selectedIds;
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [-71.8, 42.25],
      zoom: 7.1,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          osm: {type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors"},
        },
        layers: [{id: "osm", type: "raster", source: "osm", paint: {"raster-saturation": -0.75, "raster-opacity": 0.88}}],
      },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-right");
    map.addControl(new maplibregl.AttributionControl({compact: true}), "bottom-right");

    map.on("load", () => {
      if (mapRef.current !== map) return;
      map.addSource(SOURCE_ID, {type: "geojson", data: asMapData(dataRef.current, selectedRef.current)});
      map.addLayer({
        id: POINT_LAYER,
        type: "circle",
        source: SOURCE_ID,
        filter: ["!=", ["get", "selected"], 1],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "population"], 0, 4, 10000, 7, 75000, 13],
          "circle-color": ["interpolate", ["linear"], ["get", "equity"], 0, "#94a3b8", 35, "#30a69a", 70, "#075e58", 100, "#173f3b"],
          "circle-opacity": 0.82,
          "circle-stroke-width": 1.2,
          "circle-stroke-color": "#ffffff",
        },
      });
      map.addLayer({
        id: SELECTED_LAYER,
        type: "circle",
        source: SOURCE_ID,
        filter: ["==", ["get", "selected"], 1],
        paint: {"circle-radius": 12, "circle-color": "#f2b84b", "circle-stroke-color": "#5c3400", "circle-stroke-width": 3},
      });

      const handleClick = (event: maplibregl.MapLayerMouseEvent) => {
        const mapFeature = event.features?.[0];
        const id = String(mapFeature?.id ?? mapFeature?.properties?.municipality ?? "");
        const feature = dataRef.current.features.find((item) => item.id === id);
        if (!feature || !feature.geometry) return;
        onSelectRef.current(feature);
        const population = feature.properties.ej_subset_population?.toLocaleString() ?? "Not available";
        const equity = feature.properties.population_weighted_percent_minority_ej_subset;
        new maplibregl.Popup({offset: 12, closeButton: true})
          .setLngLat(feature.geometry.coordinates)
          .setHTML(`<strong>${escapeText(feature.id)}</strong><span>EJ-subset population: ${population}</span><span>Minority population (weighted): ${equity === null ? "Not available" : `${equity.toFixed(1)}%`}</span><small>Representative analytical point — not a boundary or venue</small>`)
          .addTo(map);
      };
      [POINT_LAYER, SELECTED_LAYER].forEach((layer) => {
        map.on("click", layer, handleClick);
        map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
      });
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const source = mapRef.current?.getSource(SOURCE_ID) as GeoJSONSource | undefined;
    source?.setData(asMapData(data, selectedIds));
  }, [data, selectedIds]);

  return <div ref={containerRef} className={styles.map} role="region" aria-label="Massachusetts municipality analytical point map" />;
}
