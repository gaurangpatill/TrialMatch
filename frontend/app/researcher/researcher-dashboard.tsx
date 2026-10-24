"use client";

import {useCallback, useEffect, useMemo, useRef, useState} from "react";

import ResearcherMap from "./researcher-map";
import styles from "./researcher.module.css";
import type {BaselineResult, ConstraintSatisfaction, GeoCollection, GeoFeature, OptimizeResponse} from "./types";

const integer = new Intl.NumberFormat("en-US", {maximumFractionDigits: 0});
const decimal = new Intl.NumberFormat("en-US", {maximumFractionDigits: 2});
const percent = new Intl.NumberFormat("en-US", {maximumFractionDigits: 1, signDisplay: "exceptZero"});

type WorkspaceMode = "access" | "planning";
type MapPlan = {result: OptimizeResponse; radiusKm: number};

function apiBase() {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
}

function apiUrl(path: string) {
  return `${apiBase()}${path}`;
}

async function errorMessage(response: Response) {
  try {
    const body = await response.json() as {detail?: string | {code?: string; message?: string} | Array<{msg?: string}>; error?: {message?: string}};
    if (typeof body.detail === "string") return body.detail;
    if (body.detail && !Array.isArray(body.detail) && body.detail.message) return body.detail.message;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail.map((item) => item.msg).filter(Boolean).join("; ");
    if (body.error?.message) return body.error.message;
  } catch {
    // Use the status fallback when the response is not JSON.
  }
  return `Request failed (${response.status} ${response.statusText || "Unknown error"}).`;
}

function formatDate(value?: string | null) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Unavailable" : date.toLocaleString("en-US", {dateStyle: "medium", timeStyle: "short"});
}

function nullableInteger(value: number | null | undefined) {
  return value === null || value === undefined ? "Unavailable" : integer.format(value);
}

function nullablePercent(value: number | null | undefined) {
  return value === null || value === undefined ? "Unavailable" : `${decimal.format(value)}%`;
}

function Metric({label, value, help}: {label: string; value: string; help?: string}) {
  return <div className={styles.metric} title={help}><span>{label}</span><strong>{value}</strong></div>;
}

function ConstraintLabel({constraints}: {constraints: ConstraintSatisfaction}) {
  return <span className={constraints.all_satisfied ? styles.ok : styles.bad}>{constraints.all_satisfied ? "All constraints satisfied" : "Constraint check failed"}</span>;
}

function strategyLabel(strategy: BaselineResult["strategy"]) {
  return strategy === "population_first_greedy" ? "Population-first greedy" : "Equity-first greedy";
}

function strategyDescription(name: string) {
  if (name === "Optimized plan") return "Tests the full mathematical model to find the best validated objective value under the submitted limits.";
  if (name === "Population-first greedy") return "Adds locations step by step, prioritizing modeled EJ-subset population coverage without searching all combinations.";
  return "Adds locations step by step using the modeled equity priority without searching all combinations.";
}

function improvementLabel(optimized: number, baseline: number) {
  const difference = optimized - baseline;
  if (difference === 0) return "Tie — same objective";
  if (baseline === 0) return `${decimal.format(difference)} objective points higher; percentage unavailable because the baseline is zero`;
  return `${decimal.format(difference)} objective points (${percent.format((difference / baseline) * 100)}%) ${difference > 0 ? "higher" : "lower"}`;
}

function accessValue(feature: GeoFeature) {
  const nearby = feature.properties.distinct_nearby_recruiting_nct_count;
  if (nearby === null) return "Unavailable — clinical-site access was not calculated";
  if (nearby === 0) return "0 — no matching NCTs within the applied radius";
  return integer.format(nearby);
}

export default function ResearcherDashboard() {
  const [mode, setMode] = useState<WorkspaceMode>("access");
  const [geo, setGeo] = useState<GeoCollection | null>(null);
  const [planningGeo, setPlanningGeo] = useState<GeoCollection | null>(null);
  const [geoLoading, setGeoLoading] = useState(true);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [condition, setCondition] = useState("");
  const [accessRadius, setAccessRadius] = useState(25);
  const [appliedCondition, setAppliedCondition] = useState("");
  const [appliedAccessRadius, setAppliedAccessRadius] = useState(25);
  const [maxEvents, setMaxEvents] = useState(5);
  const [radius, setRadius] = useState(25);
  const [equity, setEquity] = useState(0.5);
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [mapPlan, setMapPlan] = useState<MapPlan | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [optimizeError, setOptimizeError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [activeFeature, setActiveFeature] = useState<GeoFeature | null>(null);
  const geoAbortRef = useRef<AbortController | null>(null);
  const geoRequestRef = useRef(0);
  const optimizeAbortRef = useRef<AbortController | null>(null);
  const optimizeRequestRef = useRef(0);

  const loadGeo = useCallback(async (nextCondition: string, nextRadius: number) => {
    geoAbortRef.current?.abort();
    const controller = new AbortController();
    const requestId = ++geoRequestRef.current;
    geoAbortRef.current = controller;
    setGeoLoading(true);
    setGeoError(null);
    const parameters = new URLSearchParams();
    if (nextCondition) parameters.set("condition", nextCondition);
    parameters.set("access_radius_km", String(nextRadius));
    try {
      const response = await fetch(`${apiUrl("/api/geo")}?${parameters.toString()}`, {signal: controller.signal, headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error(await errorMessage(response));
      const nextGeo = await response.json() as GeoCollection;
      if (requestId !== geoRequestRef.current) return;
      setGeo(nextGeo);
      if (!nextCondition) setPlanningGeo(nextGeo);
      setAppliedCondition(nextCondition);
      setAppliedAccessRadius(nextRadius);
      setActiveFeature(null);
    } catch (error) {
      if (controller.signal.aborted || requestId !== geoRequestRef.current) return;
      setGeoError(error instanceof Error ? error.message : "Unable to load municipality and recruiting-site data.");
    } finally {
      if (requestId === geoRequestRef.current) setGeoLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGeo("", 25);
    return () => {
      geoAbortRef.current?.abort();
      optimizeAbortRef.current?.abort();
    };
  }, [loadGeo]);

  const markChanged = () => {
    if (result) setStale(true);
    setOptimizeError(null);
  };

  const runOptimization = async () => {
    optimizeAbortRef.current?.abort();
    const controller = new AbortController();
    const requestId = ++optimizeRequestRef.current;
    const submittedRadius = radius;
    optimizeAbortRef.current = controller;
    setOptimizing(true);
    setOptimizeError(null);
    setMapPlan(null);
    if (result) setStale(true);
    try {
      const response = await fetch(apiUrl("/api/optimize"), {
        method: "POST",
        signal: controller.signal,
        headers: {"Content-Type": "application/json", Accept: "application/json"},
        body: JSON.stringify({max_events: maxEvents, coverage_radius_km: submittedRadius, equity_weight: equity}),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const nextResult = await response.json() as OptimizeResponse;
      if (requestId !== optimizeRequestRef.current) return;
      setResult(nextResult);
      setMapPlan({result: nextResult, radiusKm: submittedRadius});
      setStale(false);
      setActiveFeature(null);
    } catch (error) {
      if (controller.signal.aborted || requestId !== optimizeRequestRef.current) return;
      setOptimizeError(error instanceof Error ? error.message : "The optimization request failed.");
    } finally {
      if (requestId === optimizeRequestRef.current) setOptimizing(false);
    }
  };

  const mapGeo = mode === "planning" ? planningGeo ?? geo : geo;
  const mapSelectedLocations = mode === "planning" ? mapPlan?.result.selected_locations ?? [] : [];
  const mapCoveredIds = useMemo(() => new Set(mode === "planning" ? mapPlan?.result.covered_municipality_ids ?? [] : []), [mapPlan, mode]);
  const comparison = result ? [
    {name: "Optimized plan", events: result.total_events, covered: result.covered_municipality_count, population: result.modeled_ej_subset_population_proxy_covered, objective: result.modeled_outreach_coverage_objective, constraints: result.constraint_satisfaction, selected: result.selected_locations.map((location) => location.municipality_id)},
    ...result.baselines.map((baseline) => ({name: strategyLabel(baseline.strategy), events: baseline.total_events, covered: baseline.covered_community_ids.length, population: baseline.modeled_ej_subset_population_proxy_covered, objective: baseline.modeled_outreach_coverage_objective, constraints: baseline.constraint_satisfaction, selected: baseline.selected_municipality_ids})),
  ] : [];
  const conditionLabel = appliedCondition || "All exported recruiting sites";
  const resolvedSites = geo?.recruiting_site_features.filter((feature) => feature.geometry).length;

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brand}><div className={styles.mark} aria-hidden="true">T+</div><div><strong>TrialMatch</strong><span>Research access planning</span></div></div>
        <div className={styles.headerMeta}><span><i className={styles.statusDot} />Modeled planning environment</span><span>Researcher workspace</span></div>
      </header>

      <main className={styles.main}>
        <section className={styles.intro} aria-labelledby="workspace-title">
          <div><span className={styles.eyebrow}>Researcher workspace</span><h1 id="workspace-title">Trial access and outreach planning</h1><p>Explore recruiting-site access separately from transparent, condition-independent outreach optimization.</p></div>
          <div className={styles.freshness}>{geo ? <><strong>{integer.format(geo.summary.observed_feature_count)} municipalities observed</strong><br />Source retrieved {formatDate(geo.summary.retrieved_at)}</> : "Loading source summary…"}</div>
        </section>

        <nav className={styles.modeTabs} aria-label="Researcher analysis mode">
          <button type="button" className={mode === "access" ? styles.modeActive : ""} aria-pressed={mode === "access"} onClick={() => setMode("access")}><span>01</span> Explore trial access by condition</button>
          <button type="button" className={mode === "planning" ? styles.modeActive : ""} aria-pressed={mode === "planning"} onClick={() => setMode("planning")}><span>02</span> Plan equitable outreach</button>
        </nav>

        <div className={styles.workspace}>
          <aside className={styles.panel} aria-labelledby="controls-heading">
            {mode === "access" ? <>
              <div className={styles.panelHead}><h2 id="controls-heading">Explore trial access by condition</h2><span className={styles.step}>Access view</span></div>
              <label className={styles.field}><span className={styles.fieldLabel}>Recruiting trial condition</span><select value={condition} disabled={geoLoading || !geo?.summary.clinical_site_data_available} onChange={(event) => setCondition(event.target.value)}><option value="">All exported recruiting sites</option>{geo?.available_conditions?.map((item) => <option value={item} key={item}>{item}</option>)}</select><small className={styles.hint}>Case, Unicode width, and surrounding whitespace are normalized for exact label matching. No fuzzy synonyms or medical equivalence are inferred.</small></label>
              <label className={styles.field}><span className={styles.fieldLabel}>Nearby-site radius <output className={styles.value}>{accessRadius} km</output></span><span className={styles.dual}><input aria-label="Nearby-site radius slider" type="range" min={0} max={200} step={1} value={accessRadius} disabled={geoLoading} onChange={(event) => setAccessRadius(Number(event.target.value))} /><input aria-label="Nearby-site radius in kilometers" type="number" min={0} max={200} step={1} value={accessRadius} disabled={geoLoading} onChange={(event) => setAccessRadius(Math.min(200, Math.max(0, Number(event.target.value))))} /></span><small className={styles.hint}>Counts distinct matching NCT IDs around each representative municipality point using straight-line distance.</small></label>
              <button className={styles.run} type="button" onClick={() => void loadGeo(condition, accessRadius)} disabled={geoLoading || !geo?.summary.clinical_site_data_available}>{geoLoading ? "Loading access view…" : "Apply access view"}</button>
              {!geo?.summary.clinical_site_data_available && !geoLoading && <p className={styles.changed}>Clinical-site export unavailable. Conditions, sites, and municipality access values remain unavailable—not zero.</p>}
              {geoError && <p className={styles.error} role="alert"><strong>Access data failed to load.</strong><br />{geoError}</p>}
              {geo && <div className={styles.scopeCard} aria-label="Clinical export scope"><strong>{conditionLabel}</strong><dl><dt>Matching site records</dt><dd>{nullableInteger(geo.summary.clinical_site_retained_count)}</dd><dt>Distinct studies</dt><dd>{nullableInteger(geo.summary.clinical_site_distinct_nct_count)}</dd><dt>Resolved / unresolved</dt><dd>{nullableInteger(geo.summary.clinical_site_resolved_count)} / {nullableInteger(geo.summary.clinical_site_unresolved_count)}</dd><dt>Quarantined</dt><dd>{nullableInteger(geo.summary.clinical_site_quarantined_count)}</dd></dl>{geo.summary.clinical_site_data_available && resolvedSites === 0 && <p className={styles.empty}><strong>0 resolved matching sites.</strong> No site points can be mapped for this exact view.</p>}</div>}
            </> : <>
              <div className={styles.panelHead}><h2 id="controls-heading">Plan equitable outreach</h2><span className={styles.step}>Planning view</span></div>
              <p className={styles.modeNote}>This optimizer is condition-independent. The selected trial condition is never sent to optimization.</p>
              <label className={styles.field}><span className={styles.fieldLabel}>How many outreach events? <output className={styles.value}>{maxEvents}</output></span><input disabled={optimizing} type="number" min={0} max={20} step={1} value={maxEvents} onChange={(event) => {setMaxEvents(Math.min(20, Math.max(0, Math.round(Number(event.target.value))))); markChanged();}} /><small className={styles.hint}>Zero is valid and returns an empty plan with no catchment circles.</small></label>
              <label className={styles.field}><span className={styles.fieldLabel}>How far can each event reach? <output className={styles.value}>{radius} km</output></span><span className={styles.dual}><input disabled={optimizing} aria-label="Outreach reach slider" type="range" min={0} max={200} step={1} value={radius} onChange={(event) => {setRadius(Number(event.target.value)); markChanged();}} /><input disabled={optimizing} aria-label="Outreach reach in kilometers" type="number" min={0} max={200} step={1} value={radius} onChange={(event) => {setRadius(Math.min(200, Math.max(0, Number(event.target.value)))); markChanged();}} /></span><small className={styles.hint}>Straight-line geodesic approximation—not travel time or a service area.</small></label>
              <label className={styles.field}><span className={styles.fieldLabel}>How strongly should we prioritize underserved communities? <output className={styles.value}>{equity.toFixed(2)}</output></span><input disabled={optimizing} aria-label="Underserved community priority" type="range" min={0} max={1} step={0.05} value={equity} onChange={(event) => {setEquity(Number(event.target.value)); markChanged();}} /><small className={styles.hint}>0 emphasizes population coverage; 1 applies the full modeled equity priority.</small></label>
              <button className={styles.run} type="button" onClick={() => void runOptimization()} disabled={optimizing || geoLoading}>{optimizing ? "Finding the best outreach plan…" : "Find the best outreach plan"}</button>
              {stale && <p className={styles.changed} role="status"><strong>{optimizing ? "Optimization running." : "Scenario changed."}</strong> Existing result cards are retained for reference. Map selections and catchments are cleared during a new request.</p>}
              {optimizeError && <p className={styles.error} role="alert"><strong>Optimization failed.</strong><br />{optimizeError}</p>}
            </>}
          </aside>

          <section className={styles.mapCard} aria-labelledby="map-heading">
            <div className={styles.mapTitle}><strong id="map-heading">{mode === "access" ? conditionLabel : "Condition-independent outreach plan"}</strong><span>{mode === "access" ? `Access within ${appliedAccessRadius} km · exact exported condition` : mapPlan ? `${mapPlan.radiusKm} km submitted reach · straight-line geodesic approximation` : "Run a plan to show selections and catchments"}</span></div>
            {!geo && geoLoading && <p className={styles.loading} role="status">Loading persisted municipality and recruiting-site geography…</p>}
            {!geo && geoError && <div className={styles.mapError} role="alert"><strong>Map data unavailable.</strong><br />{geoError}<br /><button type="button" onClick={() => void loadGeo(condition, accessRadius)}>Retry geography request</button></div>}
            {mapGeo && <ResearcherMap data={mapGeo} selectedLocations={mapSelectedLocations} coveredIds={mapCoveredIds} submittedRadiusKm={mode === "planning" ? mapPlan?.radiusKm ?? null : null} visualizationMode={mode} onSelect={setActiveFeature} />}
            {geoLoading && geo && <div className={styles.mapLoading} role="status">Refreshing access data…</div>}
            {geo && <div className={styles.legend} aria-label={`${mode === "access" ? conditionLabel : "Outreach plan"} map legend`}><div className={styles.legendTitle}>{mode === "access" ? conditionLabel : "Plan coverage"}</div>{mode === "access" ? <><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotAccessHigh}`} /> More nearby distinct NCTs</div><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotAccessZero}`} /> 0 nearby matching NCTs</div><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotUnavailable}`} /> Access unavailable</div><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotSite}`} /> Recruiting site / cluster</div></> : <><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotLow}`} /> Uncovered EJ community</div><div className={styles.legendRow}><i className={styles.dot} /> Covered EJ community</div><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotSelected}`} /> Selected outreach location</div><div className={styles.legendRow}><i className={`${styles.legendCatchment}`} /> Submitted-radius catchment</div><div className={styles.legendRow}><i className={`${styles.dot} ${styles.dotSite}`} /> Recruiting site / cluster</div></>}</div>}
            {activeFeature && <div className={styles.details}><button type="button" aria-label="Close municipality details" onClick={() => setActiveFeature(null)}>×</button><strong>{activeFeature.id}</strong><dl><dt>EJ-subset population</dt><dd>{nullableInteger(activeFeature.properties.ej_subset_population)}</dd><dt>Weighted minority</dt><dd>{nullablePercent(activeFeature.properties.population_weighted_percent_minority_ej_subset)}</dd><dt>Limited-English HH</dt><dd>{nullablePercent(activeFeature.properties.population_weighted_limited_english_household_percent_ej_subset)}</dd><dt>Mean block-group median income</dt><dd>{activeFeature.properties.population_weighted_mean_block_group_median_household_income_usd_ej_subset === null ? "Unavailable" : `$${integer.format(activeFeature.properties.population_weighted_mean_block_group_median_household_income_usd_ej_subset)}`}</dd><dt>Nearby distinct NCTs</dt><dd>{accessValue(activeFeature)}</dd><dt>Nearest matching trial</dt><dd>{activeFeature.properties.nearest_resolved_recruiting_site_distance_km === null ? (activeFeature.properties.distinct_nearby_recruiting_nct_count === null ? "Unavailable" : "No resolved matching site") : `${decimal.format(activeFeature.properties.nearest_resolved_recruiting_site_distance_km)} km`}</dd></dl></div>}
          </section>
        </div>

        {mode === "access" ? <section className={styles.accessReport} aria-labelledby="scope-heading">
          <div><span className={styles.eyebrow}>Clinical export scope</span><h2 id="scope-heading">What this access view contains</h2><p>Only the expanded recruiting cohort described by the loaded export is shown—not every study or site in ClinicalTrials.gov.</p></div>
          <div className={styles.scopeMetrics}><Metric label="Source records" value={nullableInteger(geo?.summary.clinical_site_source_record_count)} /><Metric label="Source snapshot studies" value={nullableInteger(geo?.summary.clinical_site_source_snapshot_study_count)} /><Metric label="Expanded studies" value={nullableInteger(geo?.summary.clinical_site_expanded_study_count)} /><Metric label="Exported studies" value={nullableInteger(geo?.summary.clinical_site_exported_study_count)} /></div>
          <dl className={styles.wideDl}><dt>Export cohort</dt><dd>{geo?.summary.clinical_site_export_scope ?? "Unavailable"}</dd><dt>Coordinates</dt><dd>{geo?.summary.clinical_site_coordinate_precision_limitation ?? "Unavailable"}</dd><dt>Export generated</dt><dd>{formatDate(geo?.summary.clinical_site_export_generated_at)}</dd><dt>Limitations</dt><dd>{geo?.summary.clinical_site_export_limitations?.join(" · ") ?? "Unavailable"}</dd></dl>
        </section> : <section className={styles.results} aria-label="Optimization results" aria-live="polite">
          <article className={styles.card}>
            <div className={styles.statusRow}><div><span className={styles.eyebrow}>Plan summary</span><h2>Optimization result</h2></div>{result && <span className={`${styles.badge} ${result.status === "optimal" || result.status === "feasible" ? "" : styles.badgeWarn}`}>{result.status}</span>}</div>
            {!result && <p className={styles.empty}>Configure the scenario and find the best outreach plan. No result or map selection is prefilled.</p>}
            {result && <><div className={styles.metricGrid}><Metric label="Events" value={integer.format(result.total_events)} /><Metric label="Distinct covered" value={integer.format(result.covered_municipality_count)} help="Unique municipalities covered across all selected catchments." /><Metric label="EJ population proxy" value={integer.format(result.modeled_ej_subset_population_proxy_covered)} /><Metric label="Modeled objective" value={decimal.format(result.modeled_outreach_coverage_objective)} /></div><div className={styles.solver}>Solver: {result.solver.name} {result.solver.version}<br />Native status: {result.solver.native_status ?? "Unavailable"} · MIP gap: {result.solver.mip_gap === null ? "Unavailable" : decimal.format(result.solver.mip_gap)}<br />{result.solver.message}</div><div className={styles.constraint}><span>Validation</span><ConstraintLabel constraints={result.constraint_satisfaction} /></div></>}
          </article>

          <article className={`${styles.card} ${styles.whyCard}`}><span className={styles.eyebrow}>Decision transparency</span><h2>Why these locations</h2>{!result ? <p className={styles.empty}>Location-level catchment and fixed-plan contribution details appear after optimization.</p> : result.selected_locations.length === 0 ? <p className={styles.empty}>No locations were selected. This is a valid empty plan when zero events are allowed.</p> : <div className={styles.explanationGrid}>{result.selected_locations.map((location, index) => <section className={styles.explanation} key={location.municipality_id}><div className={styles.explanationHead}><span>{index + 1}</span><div><h3>{location.municipality_id}</h3><small>{integer.format(location.explanation.selected_municipality_ej_subset_population)} EJ-subset population · {nullablePercent(location.explanation.selected_municipality_percent_minority_ej_subset)} weighted minority · {nullablePercent(location.explanation.selected_municipality_limited_english_household_percent_ej_subset)} limited-English HH</small></div></div><div className={styles.explanationMetrics}><Metric label="Raw catchment" value={`${integer.format(location.explanation.raw_catchment_community_count)} communities`} help="Overlaps with other selected catchments; do not sum as distinct coverage." /><Metric label="Raw population / objective" value={`${integer.format(location.explanation.raw_catchment_ej_subset_population_proxy)} / ${decimal.format(location.explanation.raw_catchment_objective)}`} help="Raw catchment values overlap with other selections." /><Metric label="Uniquely covered" value={`${integer.format(location.explanation.uniquely_covered_community_count)} communities`} /><Metric label="Unique population / objective" value={`${integer.format(location.explanation.uniquely_covered_ej_subset_population_proxy)} / ${decimal.format(location.explanation.uniquely_covered_objective)}`} /><Metric label="Fixed-plan removal loss" value={decimal.format(location.explanation.leave_one_out_objective_loss)} help="Other selected locations remain fixed; this is not causal impact or a reoptimized marginal value." /></div><p><strong>Interpret carefully:</strong> raw catchments overlap and must not be summed as distinct coverage. Removal loss keeps the other selected locations fixed; it is not causal impact and is not a reoptimized marginal value.</p></section>)}</div>}</article>

          <article className={`${styles.card} ${styles.compareCard}`}><span className={styles.eyebrow}>Benchmarking</span><h2>How the plan compares</h2>{!result ? <p className={styles.empty}>The optimized plan and two transparent greedy baselines will be compared in the same modeled objective units.</p> : <div className={styles.strategyGrid}>{comparison.map((row, index) => <section className={styles.strategyCard} key={row.name}><div className={styles.statusRow}><h3>{row.name}</h3><ConstraintLabel constraints={row.constraints} /></div><p>{strategyDescription(row.name)}</p><dl><dt>Events</dt><dd>{integer.format(row.events)}</dd><dt>Distinct covered</dt><dd>{integer.format(row.covered)}</dd><dt>Population proxy</dt><dd>{integer.format(row.population)}</dd><dt>Objective</dt><dd>{decimal.format(row.objective)}</dd><dt>Selected municipalities</dt><dd>{row.selected.length ? row.selected.join(", ") : "None"}</dd>{index > 0 && <><dt>Optimized improvement</dt><dd>{improvementLabel(result.modeled_outreach_coverage_objective, row.objective)}</dd></>}</dl></section>)}</div>}
            <details className={styles.methodology}><summary>Detailed methodology and solver information</summary>{result ? <><p>The optimized method evaluates the formal coverage model. Greedy methods make sequential choices and are transparent benchmarks, not equivalent solvers. Objective comparisons use the actual returned objective values; raw catchment totals are not added together.</p><p><strong>Scenario:</strong> {result.scenario_construction.scenario_label}. {result.scenario_construction.equity_normalization_method} {result.scenario_construction.equity_interpretation}</p><p><strong>Construction:</strong> {result.scenario_construction.included_municipality_count} included; {result.scenario_construction.excluded_municipality_count} excluded. {result.scenario_construction.event_cost_assumption}</p><p><strong>Assumptions:</strong> {[...result.assumptions, ...result.scenario_construction.assumptions].join(" · ")}</p></> : <p>Run optimization to inspect the submitted scenario methodology.</p>}</details>
          </article>
        </section>}

        <section className={styles.notice} aria-labelledby="interpretation-heading"><strong id="interpretation-heading">Interpretation guardrails</strong><ul><li>Municipality points are analytical representatives derived from EJ block-group polygon centroids—not boundaries, outreach venues, or patient locations.</li><li>Recruiting-site coordinates are approximate source points, not independently verified facility entrances.</li><li>Radius coverage uses straight-line distance; it does not model roads, transit, travel time, eligibility, or site capacity.</li><li>Population and equity values describe aggregate EJ-flagged block-group subsets, not individuals or full-municipality statistics.</li><li>Modeled coverage is a planning objective, not enrollment, access received, eligibility, or causal impact.</li>{result?.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section>

        <section className={styles.provenance} aria-labelledby="provenance-heading"><div><h2 id="provenance-heading">Data provenance & methodology</h2><p>Official persisted source data; the optimizer performs no runtime MassGIS fetch. Source freshness reflects API provenance, not live updates.</p></div><dl><dt>Municipality source</dt><dd>{geo ? <a href={geo.summary.source_url} target="_blank" rel="noreferrer">{geo.summary.source_name}</a> : "Unavailable"}</dd><dt>Observed / resolved</dt><dd>{geo ? `${geo.summary.observed_feature_count} / ${geo.summary.resolved_feature_count} (${geo.summary.output_crs})` : "Unavailable"}</dd><dt>Clinical export</dt><dd>{geo ? geo.summary.clinical_site_data_available ? `${nullableInteger(geo.summary.clinical_site_source_record_count)} source records / ${nullableInteger(geo.summary.clinical_site_source_snapshot_study_count)} source studies; ${nullableInteger(geo.summary.clinical_site_resolved_count)} resolved, ${nullableInteger(geo.summary.clinical_site_unresolved_count)} unresolved, ${nullableInteger(geo.summary.clinical_site_quarantined_count)} quarantined` : "Unavailable; access metrics are unavailable, not zero" : "Unavailable"}</dd><dt>Coordinate method</dt><dd>{geo?.summary.coordinate_method ?? "Unavailable"}</dd><dt>Optimization generated</dt><dd>{result ? formatDate(result.generated_at) : "Not run"}</dd><dt>Optimization scope</dt><dd>Condition-independent only; condition is never included in the optimization request.</dd></dl></section>
      </main>
    </div>
  );
}
