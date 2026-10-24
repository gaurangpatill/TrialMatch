"use client";

import {useCallback, useEffect, useMemo, useState} from "react";

import ResearcherMap from "./researcher-map";
import styles from "./researcher.module.css";
import type {BaselineResult, ConstraintSatisfaction, GeoCollection, GeoFeature, OptimizeResponse} from "./types";

const integer = new Intl.NumberFormat("en-US", {maximumFractionDigits: 0});
const decimal = new Intl.NumberFormat("en-US", {maximumFractionDigits: 2});

function apiBase() {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
}

function apiUrl(path: string) {
  return `${apiBase()}${path}`;
}

async function errorMessage(response: Response) {
  try {
    const body = await response.json() as {detail?: string | {code?: string; message?: string}; error?: {message?: string}};
    if (typeof body.detail === "string") return body.detail;
    if (body.detail?.message) return body.detail.message;
    if (body.error?.message) return body.error.message;
  } catch {
    // Use the status fallback when the response is not JSON.
  }
  return `Request failed (${response.status} ${response.statusText || "Unknown error"}).`;
}

function formatDate(value?: string) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Not available" : date.toLocaleString("en-US", {dateStyle: "medium", timeStyle: "short"});
}

function Metric({label, value}: {label: string; value: string}) {
  return <div className={styles.metric}><span>{label}</span><strong>{value}</strong></div>;
}

function ConstraintLabel({constraints}: {constraints: ConstraintSatisfaction}) {
  return <span className={constraints.all_satisfied ? styles.ok : styles.bad}>{constraints.all_satisfied ? "All constraints satisfied" : "Constraint check failed"}</span>;
}

function strategyLabel(strategy: BaselineResult["strategy"]) {
  return strategy === "population_first_greedy" ? "Population-first" : "Equity-first";
}

export default function ResearcherDashboard() {
  const [geo, setGeo] = useState<GeoCollection | null>(null);
  const [geoLoading, setGeoLoading] = useState(true);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [maxEvents, setMaxEvents] = useState(5);
  const [radius, setRadius] = useState(25);
  const [equity, setEquity] = useState(0.5);
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [optimizeError, setOptimizeError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [activeFeature, setActiveFeature] = useState<GeoFeature | null>(null);

  const loadGeo = useCallback(async (signal?: AbortSignal) => {
    setGeoLoading(true);
    setGeoError(null);
    try {
      const response = await fetch(apiUrl("/api/geo"), {signal, headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error(await errorMessage(response));
      setGeo(await response.json() as GeoCollection);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setGeoError(error instanceof Error ? error.message : "Unable to load municipality data.");
    } finally {
      if (!signal?.aborted) setGeoLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadGeo(controller.signal);
    return () => controller.abort();
  }, [loadGeo]);

  const markChanged = () => {
    if (result) setStale(true);
    setOptimizeError(null);
  };

  const runOptimization = async () => {
    setOptimizing(true);
    setOptimizeError(null);
    try {
      const response = await fetch(apiUrl("/api/optimize"), {
        method: "POST",
        headers: {"Content-Type": "application/json", Accept: "application/json"},
        body: JSON.stringify({max_events: maxEvents, coverage_radius_km: radius, equity_weight: equity}),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const nextResult = await response.json() as OptimizeResponse;
      setResult(nextResult);
      setStale(false);
      setActiveFeature(null);
    } catch (error) {
      setOptimizeError(error instanceof Error ? error.message : "The optimization request failed.");
    } finally {
      setOptimizing(false);
    }
  };

  const selectedIds = useMemo(() => new Set(result?.selected_locations.map((item) => item.municipality_id) ?? []), [result]);
  const selectedById = useMemo(() => new Map(geo?.features.map((feature) => [feature.id, feature]) ?? []), [geo]);
  const comparison = result ? [
    {name: "MILP", events: result.total_events, covered: result.covered_municipality_count, population: result.modeled_ej_subset_population_proxy_covered, objective: result.modeled_outreach_coverage_objective, constraints: result.constraint_satisfaction},
    ...result.baselines.map((baseline) => ({name: strategyLabel(baseline.strategy), events: baseline.total_events, covered: baseline.covered_community_ids.length, population: baseline.modeled_ej_subset_population_proxy_covered, objective: baseline.modeled_outreach_coverage_objective, constraints: baseline.constraint_satisfaction})),
  ] : [];

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}><div className={styles.mark} aria-hidden="true">T+</div><div><strong>TrialMatch</strong><span>Research access planning</span></div></div>
        <div className={styles.headerMeta}><span><i className={styles.statusDot} />Modeled planning environment</span><span>Researcher workspace</span></div>
      </header>

      <main className={styles.main}>
        <section className={styles.intro} aria-labelledby="workspace-title">
          <div><span className={styles.eyebrow}>Researcher workspace</span><h1 id="workspace-title">Community outreach scenario planner</h1><p>Compare transparent, condition-independent outreach plans across Massachusetts EJ-subset aggregates.</p></div>
          <div className={styles.freshness}>{geo ? <><strong>{integer.format(geo.summary.observed_feature_count)} municipalities observed</strong><br />Source retrieved {formatDate(geo.summary.retrieved_at)}</> : "Loading source summary…"}</div>
        </section>

        <div className={styles.workspace}>
          <aside className={styles.panel} aria-labelledby="scenario-heading">
            <div className={styles.panelHead}><h2 id="scenario-heading">Scenario controls</h2><span className={styles.step}>01 · Configure</span></div>
            <label className={styles.field}><span className={styles.fieldLabel}>Planning scope</span><select disabled={optimizing || !geo?.summary.clinical_site_data_available} value="independent" onChange={() => undefined}><option value="independent">Condition-independent EJ outreach</option></select><small className={styles.hint}>{geo?.summary.clinical_site_data_available ? "Only the validated condition-independent objective is currently available." : "Clinical site export unavailable. Condition-specific planning is disabled; no conditions or sites are inferred."}</small></label>
            <label className={styles.field}><span className={styles.fieldLabel}>Maximum outreach events <output className={styles.value}>{maxEvents}</output></span><input disabled={optimizing} type="number" min={0} max={20} step={1} value={maxEvents} onChange={(event) => {setMaxEvents(Math.min(20, Math.max(0, Number(event.target.value)))); markChanged();}} /></label>
            <label className={styles.field}><span className={styles.fieldLabel}>Coverage radius <output className={styles.value}>{radius} km</output></span><span className={styles.dual}><input disabled={optimizing} aria-label="Coverage radius slider" type="range" min={0} max={200} step={1} value={radius} onChange={(event) => {setRadius(Number(event.target.value)); markChanged();}} /><input disabled={optimizing} aria-label="Coverage radius in kilometers" type="number" min={0} max={200} step={1} value={radius} onChange={(event) => {setRadius(Math.min(200, Math.max(0, Number(event.target.value)))); markChanged();}} /></span><small className={styles.hint}>Straight-line analytical radius; not travel time or a service area.</small></label>
            <label className={styles.field}><span className={styles.fieldLabel}>Equity weight <output className={styles.value}>{equity.toFixed(2)}</output></span><input disabled={optimizing} aria-label="Equity weight" type="range" min={0} max={1} step={0.05} value={equity} onChange={(event) => {setEquity(Number(event.target.value)); markChanged();}} /><small className={styles.hint}>0 emphasizes population coverage; 1 applies the full modeled equity priority.</small></label>
            <button className={styles.run} type="button" onClick={() => void runOptimization()} disabled={optimizing || geoLoading}>{optimizing ? "Running optimization…" : result ? "Run fresh optimization" : "Run optimization"}</button>
            {stale && <p className={styles.changed} role="status"><strong>Scenario changed.</strong> Results and highlighted selections below are from the prior run. Run again to refresh them.</p>}
            {optimizeError && <p className={styles.error} role="alert"><strong>Optimization failed.</strong><br />{optimizeError}</p>}
          </aside>

          <section className={styles.mapCard} aria-labelledby="map-heading">
            <div className={styles.mapTitle}><strong id="map-heading">Massachusetts EJ outreach landscape</strong><span>Representative points · not boundaries or venues</span></div>
            {geoLoading && <p className={styles.loading} style={{padding: 80}} role="status">Loading persisted municipality geography…</p>}
            {geoError && <div className={styles.error} style={{margin: 70}} role="alert"><strong>Map data unavailable.</strong><br />{geoError}<br /><button type="button" onClick={() => void loadGeo()}>Retry geography request</button></div>}
            {geo && <ResearcherMap data={geo} selectedIds={selectedIds} onSelect={setActiveFeature} />}
            {geo && <div className={styles.legend} aria-label="Map legend"><div className={styles.legendTitle}>EJ-subset municipality points</div><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotLow}`} /> Lower weighted minority share</div><div className={styles.legendRow}><i className={styles.dot} /> Higher weighted minority share</div><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotSelected}`} /> Selected outreach municipality</div><div className={styles.legendRow}>Circle size reflects EJ-subset population</div></div>}
            {activeFeature && <div className={styles.details}><button type="button" aria-label="Close municipality details" onClick={() => setActiveFeature(null)}>×</button><strong>{activeFeature.id}</strong><dl><dt>EJ-subset population</dt><dd>{activeFeature.properties.ej_subset_population === null ? "N/A" : integer.format(activeFeature.properties.ej_subset_population)}</dd><dt>Weighted minority</dt><dd>{activeFeature.properties.population_weighted_percent_minority_ej_subset === null ? "N/A" : `${decimal.format(activeFeature.properties.population_weighted_percent_minority_ej_subset)}%`}</dd><dt>Limited English HH</dt><dd>{activeFeature.properties.population_weighted_limited_english_household_percent_ej_subset === null ? "N/A" : `${decimal.format(activeFeature.properties.population_weighted_limited_english_household_percent_ej_subset)}%`}</dd><dt>EJ block groups</dt><dd>{activeFeature.properties.ej_block_group_count}</dd></dl></div>}
          </section>

          <section className={styles.results} aria-label="Optimization results" aria-live="polite">
            <article className={styles.card}>
              <div className={styles.statusRow}><h2>Optimization result</h2>{result && <span className={`${styles.badge} ${result.status === "optimal" || result.status === "feasible" ? "" : styles.badgeWarn}`}>{result.status}</span>}</div>
              {!result && <p className={styles.empty}>Configure the scenario and run the optimizer to produce a plan. No selected results are prefilled.</p>}
              {result && <><div className={styles.metricGrid}><Metric label="Events" value={integer.format(result.total_events)} /><Metric label="Unique covered" value={integer.format(result.covered_municipality_count)} /><Metric label="EJ population proxy" value={integer.format(result.modeled_ej_subset_population_proxy_covered)} /><Metric label="Weighted objective" value={decimal.format(result.modeled_outreach_coverage_objective)} /></div><div className={styles.solver}>Solver: {result.solver.name} {result.solver.version}<br />Native status: {result.solver.native_status ?? "N/A"} · MIP gap: {result.solver.mip_gap === null ? "N/A" : decimal.format(result.solver.mip_gap)}<br />{result.solver.message}</div><div className={styles.constraint}><span>Validation</span><ConstraintLabel constraints={result.constraint_satisfaction} /></div></>}
            </article>

            <article className={styles.card}><h2>Selected municipalities</h2>{!result ? <p className={styles.empty}>Awaiting an optimization run.</p> : result.selected_locations.length === 0 ? <p className={styles.empty}>No municipalities selected for this scenario.</p> : <div className={styles.selection}>{result.selected_locations.map((location, index) => <div className={styles.selectionItem} key={location.municipality_id}><span>{String(index + 1).padStart(2, "0")} · {location.municipality_id}</span><span>{selectedById.get(location.municipality_id)?.properties.ej_subset_population?.toLocaleString() ?? "N/A"} proxy pop.</span></div>)}</div>}</article>

            <article className={styles.card}><h2>Strategy comparison</h2>{!result ? <p className={styles.empty}>MILP and greedy baselines will be compared in the same modeled objective units.</p> : <div className={styles.tableWrap}><table className={styles.table}><caption className={styles.srOnly}>Optimization strategy comparison</caption><thead><tr><th>Strategy</th><th>Events</th><th>Covered</th><th>EJ pop. proxy</th><th>Objective</th><th>Valid</th></tr></thead><tbody>{comparison.map((row) => <tr key={row.name}><td>{row.name}</td><td>{row.events}</td><td>{row.covered}</td><td>{integer.format(row.population)}</td><td>{decimal.format(row.objective)}</td><td>{row.constraints.all_satisfied ? "Yes" : "No"}</td></tr>)}</tbody></table></div>}</article>
          </section>
        </div>

        <section className={styles.notice} aria-labelledby="interpretation-heading"><strong id="interpretation-heading">Interpretation guardrails</strong><ul><li>Points are analytical municipality representatives derived from EJ block-group polygon centroids—not municipality boundaries, outreach venues, or patient locations.</li><li>Radius coverage uses straight-line distance; it does not model roads, transit, travel time, eligibility, or site capacity.</li><li>Population and equity values describe aggregate EJ-flagged block-group subsets, not individuals or full-municipality statistics.</li><li>Modeled coverage is a planning objective, not enrollment, access received, eligibility, or causal impact.</li>{result?.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section>

        <section className={styles.provenance} aria-labelledby="provenance-heading"><div><h2 id="provenance-heading">Data provenance & methodology</h2><p>Official persisted source data; the optimizer performs no runtime MassGIS fetch. Source freshness reflects API provenance, not live updates.</p></div><dl><dt>Source</dt><dd>{geo ? <a href={geo.summary.source_url} target="_blank" rel="noreferrer">{geo.summary.source_name}</a> : "Unavailable"}</dd><dt>Observed / resolved</dt><dd>{geo ? `${geo.summary.observed_feature_count} / ${geo.summary.resolved_feature_count} (${geo.summary.output_crs})` : "Unavailable"}</dd><dt>Clinical-site export</dt><dd>{geo ? geo.summary.clinical_site_data_available ? `Available · ${geo.summary.clinical_site_resolved_count ?? 0} resolved` : "Unavailable · condition-specific analysis disabled" : "Unknown"}</dd><dt>Coordinate method</dt><dd>{geo?.summary.coordinate_method ?? "Unavailable"}</dd><dt>Optimization generated</dt><dd>{result ? formatDate(result.generated_at) : "Not run"}</dd><dt>Scenario construction</dt><dd>{result ? `${result.scenario_construction.included_municipality_count} included; ${result.scenario_construction.excluded_municipality_count} excluded. ${result.scenario_construction.equity_normalization_method}` : "Available after optimization"}</dd><dt>Assumptions</dt><dd>{result ? [...result.assumptions, ...result.scenario_construction.assumptions].join(" · ") : "Equal abstract event costs; condition-independent outreach; persisted representative points."}</dd></dl></section>
      </main>
    </div>
  );
}
