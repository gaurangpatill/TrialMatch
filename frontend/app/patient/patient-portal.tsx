"use client";

import Link from "next/link";
import {FormEvent, useEffect, useMemo, useRef, useState} from "react";

import type {
  ApiError,
  CriterionStatus,
  ExtractionCoverageStatus,
  MatchResponse,
  ScreeningStatus,
  TrialDetail,
  TrialLocation,
  TrialSearchResponse,
  TrialSummary,
} from "@/lib/clinical-contracts";

const exampleSearches = ["Breast Cancer", "Heart Failure", "Prostate Cancer", "Colorectal Cancer"];
const phaseOptions = ["PHASE1", "PHASE2", "PHASE3", "PHASE4", "EARLY_PHASE1", "NOT_APPLICABLE", "NA"];
type FactState = "unknown" | "present" | "absent";
type SortOption = "source" | "title" | "status" | "ma_sites";

const screeningLabels: Record<ScreeningStatus, string> = {
  potential_match: "Covered requirements met — confirmation needed",
  known_mismatch: "A known requirement was not met",
  unresolved: "Cannot determine yet",
};

const criterionLabels: Record<CriterionStatus, string> = {
  met: "Requirement met",
  not_met: "Requirement not met",
  unknown: "Cannot determine",
};

export function PatientPortal() {
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [phase, setPhase] = useState("");
  const [studyAge, setStudyAge] = useState("");
  const [location, setLocation] = useState("");
  const [sort, setSort] = useState<SortOption>("source");
  const [page, setPage] = useState(1);
  const [trials, setTrials] = useState<TrialSummary[]>([]);
  const [knownTrials, setKnownTrials] = useState<Record<string, TrialSummary>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [freshness, setFreshness] = useState<string | null>(null);
  const [searching, setSearching] = useState(true);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [activeTrial, setActiveTrial] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, TrialDetail>>({});
  const [detailLoading, setDetailLoading] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [age, setAge] = useState("");
  const [sex, setSex] = useState("");
  const [conditionFacts, setConditionFacts] = useState<Record<string, FactState>>({});
  const [customCondition, setCustomCondition] = useState("");
  const [customConditions, setCustomConditions] = useState<string[]>([]);
  const [matching, setMatching] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);
  const [match, setMatch] = useState<MatchResponse | null>(null);

  const discoveryHeadingRef = useRef<HTMLHeadingElement>(null);
  const matchHeadingRef = useRef<HTMLHeadingElement>(null);
  const lastFocusedElement = useRef<HTMLElement | null>(null);
  const selectedTrials = selected.map((id) => knownTrials[id]).filter(Boolean);
  const relevantConditions = useMemo(
    () => [...new Set([...selectedTrials.flatMap((trial) => trial.conditions), ...customConditions])],
    [selectedTrials, customConditions],
  );
  const displayedTrials = useMemo(() => sortTrials(trials, sort), [trials, sort]);

  async function searchTrials(searchQuery: string, requestedPage = 1, focusResults = true) {
    const ageValue = studyAge.trim() ? Number(studyAge) : null;
    if (ageValue !== null && (!Number.isFinite(ageValue) || ageValue < 0 || ageValue > 125)) {
      setSearchError("Study age must be between 0 and 125 years.");
      return;
    }
    setSearching(true);
    setSearchError(null);
    setMatch(null);
    try {
      const normalizedQuery = searchQuery.trim();
      const parameters = new URLSearchParams({page: String(requestedPage), page_size: "12"});
      if (normalizedQuery) parameters.set("query", normalizedQuery);
      if (phase) parameters.set("phase", phase);
      if (ageValue !== null) parameters.set("age_years", String(ageValue));
      if (location.trim()) parameters.set("location", location.trim());
      const response = await fetch(`/api/trials?${parameters}`, {cache: "no-store"});
      const payload = (await response.json()) as TrialSearchResponse | ApiError;
      if (!response.ok || !("items" in payload)) {
        throw new Error(errorMessage(payload as ApiError, "Trial search failed."));
      }
      setTrials(payload.items);
      setKnownTrials((current) => {
        const next = {...current};
        payload.items.forEach((trial) => { next[trial.nct_id] = trial; });
        return next;
      });
      setAppliedQuery(normalizedQuery);
      setTotal(payload.pagination.total_items);
      setTotalPages(payload.pagination.total_pages);
      setPage(payload.pagination.page);
      setFreshness(payload.data_freshness.retrieved_at);
      if (focusResults) requestAnimationFrame(() => {
        discoveryHeadingRef.current?.focus({preventScroll: true});
        discoveryHeadingRef.current?.scrollIntoView({behavior: "smooth", block: "start"});
      });
    } catch (reason) {
      setTrials([]);
      setTotal(0);
      setTotalPages(0);
      setSearchError(reason instanceof Error ? reason.message : "Trial search failed.");
    } finally {
      setSearching(false);
    }
  }

  useEffect(() => {
    void searchTrials("", 1, false);
    // Initial curated discovery uses the local index; detail is fetched only after a study is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void searchTrials(query, 1);
  }

  function useExample(value: string) {
    setQuery(value);
    void searchTrials(value, 1);
  }

  function clearFilters() {
    setPhase("");
    setStudyAge("");
    setLocation("");
  }

  function toggleTrial(trial: TrialSummary) {
    setKnownTrials((current) => ({...current, [trial.nct_id]: trial}));
    setSelected((current) => {
      if (current.includes(trial.nct_id)) return current.filter((id) => id !== trial.nct_id);
      if (current.length >= 100) {
        setMatchError("You can compare up to 100 studies at a time.");
        return current;
      }
      return [...current, trial.nct_id];
    });
    setMatch(null);
  }

  async function openDetails(trial: TrialSummary) {
    lastFocusedElement.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setActiveTrial(trial.nct_id);
    await loadDetails(trial);
  }

  async function loadDetails(trial: TrialSummary, refresh = false) {
    setDetailError(null);
    const existing = details[trial.nct_id];
    if (!refresh && existing?.detail_status === "retrieved") return;
    setDetailLoading(trial.nct_id);
    try {
      const response = await fetch(
        `/api/trials/${encodeURIComponent(trial.nct_id)}${refresh ? "?refresh=true" : ""}`,
        {cache: "no-store"},
      );
      const payload = (await response.json()) as TrialDetail | ApiError;
      if (!response.ok || !("detail_status" in payload)) {
        throw new Error(errorMessage(payload as ApiError, "Study details could not be loaded."));
      }
      setDetails((current) => ({...current, [trial.nct_id]: payload}));
      const updated: TrialSummary = {
        ...trial,
        overall_status: payload.overall_status,
        conditions: payload.conditions,
        phases: payload.phases,
        minimum_age: payload.minimum_age,
        maximum_age: payload.maximum_age,
        sex: payload.sex,
        locations: payload.locations,
        retrieved_at: payload.retrieved_at,
        detail_status: payload.detail_status,
        screening_coverage_status: payload.screening_coverage.status,
        source_description: payload.source_description,
        plain_language_summary: payload.plain_language_summary,
      };
      setTrials((current) => current.map((item) => item.nct_id === trial.nct_id ? updated : item));
      setKnownTrials((current) => ({...current, [trial.nct_id]: updated}));
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Study details could not be loaded.");
    } finally {
      setDetailLoading(null);
    }
  }

  function closeDetails() {
    setActiveTrial(null);
    setDetailError(null);
    requestAnimationFrame(() => lastFocusedElement.current?.focus());
  }

  function addCustomCondition() {
    const value = customCondition.trim();
    if (!value) return;
    setCustomConditions((current) =>
      current.some((item) => item.toLocaleLowerCase() === value.toLocaleLowerCase()) ? current : [...current, value],
    );
    setConditionFacts((current) => ({...current, [value]: "present"}));
    setCustomCondition("");
  }

  async function runMatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected.length === 0) {
      setMatchError("Select at least one study to compare.");
      return;
    }
    const ageValue = age.trim() ? Number(age) : null;
    if (ageValue !== null && (!Number.isFinite(ageValue) || ageValue < 0 || ageValue > 125)) {
      setMatchError("Age must be between 0 and 125 years.");
      return;
    }
    setMatching(true);
    setMatchError(null);
    try {
      const presentConditions = relevantConditions.filter((item) => conditionFacts[item] === "present");
      const absentConditions = relevantConditions.filter((item) => conditionFacts[item] === "absent");
      const response = await fetch("/api/match", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({
          patient: {
            profile_id: `synthetic-browser-${Date.now()}`,
            synthetic: true,
            age_years: ageValue,
            sex: sex || null,
            conditions: presentConditions,
            medications: [],
            procedures: [],
            absent_conditions: absentConditions,
            absent_medications: [],
            absent_procedures: [],
            condition_days_ago: {},
            medication_days_ago: {},
            procedure_days_ago: {},
            laboratory_values: {},
            attributes: {},
          },
          trial_ids: selected,
          limit: Math.min(selected.length, 100),
        }),
      });
      const payload = (await response.json()) as MatchResponse | ApiError;
      if (!response.ok || !("results" in payload)) {
        throw new Error(errorMessage(payload as ApiError, "Preliminary screening failed."));
      }
      setMatch(payload);
      requestAnimationFrame(() => {
        matchHeadingRef.current?.focus({preventScroll: true});
        matchHeadingRef.current?.scrollIntoView({behavior: "smooth", block: "start"});
      });
    } catch (reason) {
      setMatch(null);
      setMatchError(reason instanceof Error ? reason.message : "Preliminary screening failed.");
    } finally {
      setMatching(false);
    }
  }

  const activeSummary = activeTrial ? knownTrials[activeTrial] : undefined;
  const activeDetail = activeTrial ? details[activeTrial] : undefined;

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-emerald-950/10 bg-white/95">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 lg:px-8">
          <Link className="text-xl font-black tracking-[-0.04em]" href="/">TrialMatch</Link>
          <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] font-bold text-amber-900 sm:text-xs">Research prototype · synthetic profiles only</span>
        </div>
      </header>

      <section className="border-b border-emerald-950/10 bg-[radial-gradient(circle_at_top_right,_#d9f4e8,_transparent_44%),linear-gradient(135deg,#f7fbf8_0%,#edf5ef_100%)]">
        <div className="mx-auto max-w-7xl px-5 py-8 sm:py-12 lg:px-8">
          <div className="max-w-4xl">
            <p className="text-xs font-black uppercase tracking-[0.18em] text-accent">Start with official study discovery</p>
            <h1 className="mt-3 max-w-3xl text-4xl font-black tracking-[-0.045em] sm:text-6xl">Find recruiting clinical studies.</h1>
            <p className="mt-4 max-w-3xl text-base leading-7 text-slate-700 sm:text-lg">Search source-grounded records, explore what each study is about, select studies to compare, then optionally practice preliminary screening with a synthetic profile.</p>
          </div>
          <form className="mt-7 max-w-5xl rounded-3xl border border-emerald-950/10 bg-white p-3 shadow-[0_24px_80px_-32px_rgba(17,33,31,0.35)] sm:p-4" onSubmit={submitSearch} role="search">
            <div className="flex flex-col gap-3 sm:flex-row">
              <label className="sr-only" htmlFor="trial-query">Condition or study keyword</label>
              <div className="flex min-w-0 flex-1 items-center gap-3 rounded-2xl bg-slate-50 px-4 ring-1 ring-inset ring-slate-200 focus-within:ring-2 focus-within:ring-accent">
                <span aria-hidden="true" className="text-xl text-slate-400">⌕</span>
                <input autoFocus className="w-full bg-transparent py-4 text-base outline-none placeholder:text-slate-400 sm:text-lg" id="trial-query" maxLength={200} onChange={(event) => setQuery(event.target.value)} placeholder="Search a condition, such as breast cancer" type="search" value={query} />
              </div>
              <button className="rounded-2xl bg-accent px-8 py-4 font-bold text-white shadow-lg shadow-teal-900/15 transition hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60" disabled={searching} type="submit">{searching ? "Searching…" : "Find studies"}</button>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 px-1 text-xs text-slate-500"><span className="font-semibold">Try:</span>{exampleSearches.map((example) => <button className="rounded-full bg-emerald-50 px-3 py-1.5 font-semibold text-emerald-800 hover:bg-emerald-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" key={example} onClick={() => useExample(example)} type="button">{example}</button>)}</div>
          </form>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-8 lg:px-8">
        <ol aria-label="How TrialMatch works" className="grid gap-3 rounded-3xl border border-slate-200 bg-white p-4 sm:grid-cols-4 sm:p-5">
          {[["1", "Search", "Use a condition or keyword."], ["2", "Explore", "Read official purpose and locations."], ["3", "Select", "Build an understandable comparison."], ["4", "Screen", "Try guided questions with synthetic facts."]].map(([step, title, text]) => <li className="flex gap-3" key={step}><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-sm font-black text-emerald-900">{step}</span><div><p className="font-black">{title}</p><p className="mt-1 text-xs leading-5 text-slate-600">{text}</p></div></li>)}
        </ol>
        <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-sm leading-6 text-amber-950 sm:flex sm:items-start sm:gap-3"><span aria-hidden="true" className="text-lg">ⓘ</span><p><strong>Preliminary research screening only.</strong> TrialMatch is not a medical device, medical advice, or a determination of eligibility. Unanswered facts stay unknown; the study team must review the complete current protocol.</p></div>

        <div className="mt-8 grid items-start gap-8 xl:grid-cols-[minmax(0,1.5fr)_minmax(360px,0.8fr)]">
          <section aria-labelledby="discovery-heading">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.2em] text-accent">Official discovery</p>
                <h2 className="mt-2 scroll-mt-4 text-3xl font-black tracking-tight outline-none" id="discovery-heading" ref={discoveryHeadingRef} tabIndex={-1}>{appliedQuery ? `Studies matching “${appliedQuery}”` : "Explore recruiting studies"}</h2>
                <p className="mt-2 text-sm text-slate-600">{total.toLocaleString()} indexed result{total === 1 ? "" : "s"}. Opening a study retrieves expanded official fields.</p>
              </div>
              <p className="text-xs text-slate-500">Index updated {formatTimestamp(freshness)}</p>
            </div>

            <details className="mt-5 rounded-2xl border border-slate-200 bg-white shadow-sm" open>
              <summary className="cursor-pointer list-none px-5 py-4 text-sm font-bold">Filter and sort results <span aria-hidden="true" className="float-right text-slate-400">＋</span></summary>
              <form className="grid gap-4 border-t border-slate-100 p-5 sm:grid-cols-2 lg:grid-cols-4" onSubmit={submitSearch}>
                <label className="text-sm font-semibold">Study phase<select className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-3 font-normal" onChange={(event) => setPhase(event.target.value)} value={phase}><option value="">Any published phase</option>{phaseOptions.map((value) => <option key={value} value={value}>{formatPhase(value)}{value === "NA" ? " (legacy source value)" : ""}</option>)}</select></label>
                <label className="text-sm font-semibold">Age to check<input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" max="125" min="0" onChange={(event) => setStudyAge(event.target.value)} placeholder="e.g. 42" step="0.1" type="number" value={studyAge} /></label>
                <label className="text-sm font-semibold">Facility, city, or state<input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" maxLength={200} onChange={(event) => setLocation(event.target.value)} placeholder="e.g. Boston" value={location} /></label>
                <label className="text-sm font-semibold">Sort this page<select className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-3 font-normal" onChange={(event) => setSort(event.target.value as SortOption)} value={sort}><option value="source">Official index order</option><option value="title">Study title A–Z</option><option value="status">Recruiting status</option><option value="ma_sites">Most Massachusetts sites</option></select></label>
                <div className="flex flex-wrap justify-end gap-3 sm:col-span-2 lg:col-span-4"><button className="rounded-xl px-4 py-2 text-sm font-bold text-slate-600 hover:bg-slate-100" onClick={clearFilters} type="button">Clear filter fields</button><button className="rounded-xl bg-ink px-5 py-2.5 text-sm font-bold text-white hover:bg-slate-800" type="submit">Apply filters</button></div>
              </form>
            </details>

            {searchError ? <Alert message={searchError} onRetry={() => void searchTrials(appliedQuery, page)} /> : null}
            <div aria-busy={searching} aria-live="polite" className="mt-5 grid gap-5">
              {searching ? <SearchSkeleton /> : null}
              {!searching && !searchError && trials.length === 0 ? <div className="rounded-3xl border border-dashed border-slate-300 bg-white p-10 text-center"><div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-xl">⌕</div><h3 className="mt-4 text-lg font-bold">No studies found</h3><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-600">Try a broader condition, remove a filter, or check another term. No study result is fabricated when the official-source index has no match.</p></div> : null}
              {!searching && displayedTrials.map((trial) => <TrialCard isSelected={selected.includes(trial.nct_id)} key={trial.nct_id} onOpen={() => void openDetails(trial)} onToggle={() => toggleTrial(trial)} selectionFull={selected.length >= 100} trial={trial} />)}
            </div>
            {totalPages > 1 && !searching ? <nav aria-label="Study result pages" className="mt-6 flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-3 text-sm"><button className="rounded-xl px-4 py-2 font-bold hover:bg-slate-100 disabled:opacity-40" disabled={page <= 1} onClick={() => void searchTrials(appliedQuery, page - 1)} type="button">← Previous</button><span className="text-slate-500">Page {page} of {totalPages}</span><button className="rounded-xl px-4 py-2 font-bold hover:bg-slate-100 disabled:opacity-40" disabled={page >= totalPages} onClick={() => void searchTrials(appliedQuery, page + 1)} type="button">Next →</button></nav> : null}
          </section>

          <aside className="xl:sticky xl:top-5">
            <form className="overflow-hidden rounded-3xl border border-emerald-950/10 bg-white shadow-[0_20px_60px_-38px_rgba(17,33,31,0.5)]" onSubmit={runMatch}>
              <div className="bg-ink p-6 text-white"><p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-300">Optional practice step</p><h2 className="mt-2 text-2xl font-black">Preliminary synthetic-profile screening</h2><p className="mt-2 text-sm leading-6 text-slate-300">Compare invented practice facts with source-backed requirements. This cannot tell a real person whether they are eligible.</p></div>
              <div className="p-5 sm:p-6">
                <div className="rounded-2xl bg-emerald-50 p-4"><div className="flex items-center justify-between gap-3"><p className="text-sm font-bold text-emerald-950">Selected-study comparison</p><span className="rounded-full bg-white px-2.5 py-1 text-xs font-black text-accent">{selected.length}/100</span></div>{selectedTrials.length ? <ul className="mt-3 space-y-3">{selectedTrials.map((trial) => <li className="rounded-xl bg-white/75 p-3 text-xs leading-5 text-emerald-950" key={trial.nct_id}><div className="flex items-start justify-between gap-2"><span className="font-bold">{trial.title}</span><button aria-label={`Remove ${trial.title}`} className="shrink-0 rounded-full px-1.5 text-base text-emerald-800 hover:bg-white" onClick={() => toggleTrial(trial)} type="button">×</button></div><p className="mt-1 text-emerald-800">{trial.phases.length ? trial.phases.map(formatPhase).join(" · ") : "Phase not specified"} · {ageLabel(trial.minimum_age, trial.maximum_age, trial.detail_status)} · {maSiteCount(trial.locations)} MA site{maSiteCount(trial.locations) === 1 ? "" : "s"}</p></li>)}</ul> : <p className="mt-2 text-xs leading-5 text-emerald-800">Select a study card to build a comparison before screening.</p>}</div>
                <div className="mt-6 rounded-2xl border border-indigo-100 bg-indigo-50 p-4 text-xs leading-5 text-indigo-950"><strong>Guided questions:</strong> Provide only invented age, registry sex field, and condition facts you want to test. Leave anything uncertain unanswered; TrialMatch will keep it unknown.</div>
                <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2"><label className="text-sm font-bold">Synthetic age <span className="font-normal text-slate-400">(optional)</span><input className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 font-normal" max="125" min="0" onChange={(event) => setAge(event.target.value)} placeholder="Unknown" step="0.1" type="number" value={age} /></label><label className="text-sm font-bold">Published sex field <span className="font-normal text-slate-400">(optional)</span><select className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-3 font-normal" onChange={(event) => setSex(event.target.value)} value={sex}><option value="">Unknown / unanswered</option><option value="female">Female</option><option value="male">Male</option></select></label></div>
                {relevantConditions.length ? <fieldset className="mt-6"><legend className="text-sm font-bold">Does the synthetic profile have each condition?</legend><p className="mt-1 text-xs leading-5 text-slate-500">Choose absent only when you explicitly want the practice profile to assert that fact.</p><div className="mt-3 space-y-3">{relevantConditions.map((condition) => <div className="rounded-xl border border-slate-200 p-3" key={condition}><p className="text-sm font-semibold">{condition}</p><div aria-label={`${condition} status`} className="mt-2 grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1" role="group">{(["unknown", "present", "absent"] as FactState[]).map((value) => { const pressed = (conditionFacts[condition] ?? "unknown") === value; return <button aria-pressed={pressed} className={`rounded-md px-2 py-1.5 text-[11px] font-bold transition ${pressed ? "bg-white text-ink shadow-sm" : "text-slate-500 hover:text-slate-800"}`} key={value} onClick={() => setConditionFacts((current) => ({...current, [condition]: value}))} type="button">{value === "unknown" ? "Unanswered" : value === "present" ? "Present" : "Absent"}</button>;})}</div></div>)}</div></fieldset> : null}
                <div className="mt-5"><p className="text-sm font-bold">Add another invented condition <span className="font-normal text-slate-400">(optional)</span></p><div className="mt-2 flex gap-2"><label className="sr-only" htmlFor="custom-condition">Condition name</label><input className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2.5 text-sm" id="custom-condition" onChange={(event) => setCustomCondition(event.target.value)} placeholder="Enter one condition" value={customCondition} /><button className="rounded-xl border border-slate-300 px-3 text-sm font-bold hover:bg-slate-50" onClick={addCustomCondition} type="button">Add</button></div></div>
                {matchError ? <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900" role="alert">{matchError}</div> : null}
                <button className="mt-6 w-full rounded-xl bg-accent px-4 py-3.5 font-bold text-white shadow-lg shadow-teal-900/10 hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-45" disabled={matching || selected.length === 0} type="submit">{matching ? "Checking provided synthetic facts…" : selected.length ? `Screen ${selected.length} selected stud${selected.length === 1 ? "y" : "ies"}` : "Select a study first"}</button><p aria-live="polite" className="mt-3 text-center text-[11px] leading-4 text-slate-500">{matching ? "Preliminary screening is in progress." : "No profile is saved by this browser experience. Use synthetic information only."}</p>
              </div>
            </form>
          </aside>
        </div>
        {match ? <MatchResults headingRef={matchHeadingRef} match={match} /> : null}
      </section>

      {activeTrial && activeSummary ? <StudyDetailPanel detail={activeDetail} error={detailError} loading={detailLoading === activeTrial} onClose={closeDetails} onRefresh={() => void loadDetails(activeSummary, true)} summary={activeSummary} /> : null}
    </main>
  );
}

function TrialCard({trial, isSelected, selectionFull, onToggle, onOpen}: {trial: TrialSummary; isSelected: boolean; selectionFull: boolean; onToggle: () => void; onOpen: () => void}) {
  const screeningReady = trial.screening_coverage_status === "partial" || trial.screening_coverage_status === "complete";
  const description = trial.plain_language_summary ?? trial.source_description;
  const descriptionLabel = trial.plain_language_summary ? "Backend-generated plain-English summary" : trial.source_description ? "Official study purpose" : null;
  return <article className={`group rounded-3xl border bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg sm:p-8 ${isSelected ? "border-accent ring-2 ring-accent/15" : "border-slate-200"}`}>
    <div className="flex flex-col gap-6 lg:flex-row lg:items-start"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2 text-[11px] font-bold uppercase tracking-wide"><span className={`rounded-full px-2.5 py-1 ${statusClass(trial.overall_status)}`}>{formatRegistryValue(trial.overall_status)}</span>{trial.phases.length ? trial.phases.slice(0, 2).map((value) => <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700" key={value}>{formatPhase(value)}</span>) : <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">Phase not specified</span>}<span className={`rounded-full px-2.5 py-1 ${screeningReady ? "bg-teal-100 text-teal-900" : "bg-indigo-50 text-indigo-700"}`}>{screeningReady ? "Structured requirements available" : "Study information only"}</span></div>
    <h3 className="mt-4 text-2xl font-black leading-8 tracking-tight sm:text-3xl">{trial.title}</h3><p className="mt-2 text-sm font-semibold text-accent">{trial.conditions.length ? trial.conditions.join(" · ") : "Condition not specified in available source fields"}</p>
    {description ? <div className="mt-4"><p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{descriptionLabel}</p><p className="mt-1 line-clamp-4 text-sm leading-6 text-slate-700">{description}</p></div> : <p className="mt-4 rounded-xl bg-slate-50 p-3 text-sm leading-6 text-slate-600">A study-purpose description is not available in the indexed source fields. Open details to retrieve the official record; TrialMatch will not invent one.</p>}
    <div className="mt-6 grid gap-4 rounded-2xl bg-slate-50 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4"><InfoItem label="Published ages" value={ageLabel(trial.minimum_age, trial.maximum_age, trial.detail_status)} /><InfoItem label="Phase" value={trial.phases.length ? trial.phases.map(formatPhase).join(", ") : "Not specified by source"} /><InfoItem label="Massachusetts facilities" value={facilityCountLabel(trial, true)} /><InfoItem label="All source facilities" value={facilityCountLabel(trial, false)} /></div>
    <p className="mt-4 text-xs text-slate-400">ClinicalTrials.gov · {trial.nct_id} · retrieved {formatTimestamp(trial.retrieved_at)}</p></div>
    <div className="flex shrink-0 gap-2 lg:w-40 lg:flex-col"><button aria-pressed={isSelected} className={`flex-1 rounded-xl px-4 py-3 text-sm font-bold ${isSelected ? "bg-emerald-100 text-emerald-900" : "bg-ink text-white hover:bg-slate-800"}`} disabled={!isSelected && selectionFull} onClick={onToggle} type="button">{isSelected ? "✓ Selected" : selectionFull ? "Limit reached" : "+ Select"}</button><button className="flex-1 rounded-xl border border-slate-300 px-4 py-3 text-sm font-bold text-slate-700 hover:border-accent hover:text-accent" onClick={onOpen} type="button">Explore details</button></div></div>
  </article>;
}

function StudyDetailPanel({summary, detail, loading, error, onClose, onRefresh}: {summary: TrialSummary; detail?: TrialDetail; loading: boolean; error: string | null; onClose: () => void; onRefresh: () => void}) {
  const displayed = detail ?? summary;
  const status = detail?.detail_status ?? summary.detail_status;
  const closeRef = useRef<HTMLButtonElement>(null);
  const maLocations = detail ? partitionLocations(detail.locations).massachusetts : [];
  const otherLocations = detail ? partitionLocations(detail.locations).other : [];
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", onKeyDown); };
  }, [onClose]);
  return <div aria-labelledby="study-detail-title" aria-modal="true" className="fixed inset-0 z-50 flex justify-end bg-ink/55 p-0 backdrop-blur-sm sm:p-4" role="dialog"><button aria-label="Close study details" className="absolute inset-0 cursor-default" onClick={onClose} type="button" /><section className="relative h-full w-full overflow-y-auto bg-canvas shadow-2xl sm:max-w-3xl sm:rounded-3xl"><div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white/95 px-5 py-4 backdrop-blur sm:px-7"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-accent">Official study details</p><p className="mt-1 text-xs text-slate-500">{summary.nct_id}</p></div><button aria-label="Close study details" className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-2xl hover:bg-slate-200" onClick={onClose} ref={closeRef} type="button">×</button></div><div className="p-5 sm:p-8">
    {loading ? <DetailSkeleton /> : null}{error ? <Alert message={error} onRetry={onRefresh} /> : null}{!loading ? <><div className="flex flex-wrap gap-2 text-[11px] font-bold uppercase tracking-wide"><span className={`rounded-full px-2.5 py-1 ${statusClass(displayed.overall_status)}`}>{formatRegistryValue(displayed.overall_status)}</span>{displayed.phases.length ? displayed.phases.map((value) => <span className="rounded-full bg-white px-2.5 py-1 text-slate-600 ring-1 ring-slate-200" key={value}>{formatPhase(value)}</span>) : <span className="rounded-full bg-white px-2.5 py-1 text-slate-600 ring-1 ring-slate-200">Phase not specified</span>}</div><h2 className="mt-4 text-3xl font-black leading-tight tracking-[-0.035em]" id="study-detail-title">{displayed.title}</h2><p className="mt-3 text-sm leading-6 text-slate-600">{displayed.conditions.length ? displayed.conditions.join(" · ") : "Conditions were not specified in the available source fields."}</p>
    <section className="mt-7 rounded-2xl border border-emerald-200 bg-white p-5"><p className="text-xs font-bold uppercase tracking-[0.16em] text-accent">What this study is about</p>{displayed.plain_language_summary ? <><p className="mt-2 text-sm font-bold text-emerald-950">Backend-generated plain-English summary</p><p className="mt-2 text-sm leading-7 text-slate-700">{displayed.plain_language_summary}</p><p className="mt-2 text-xs text-slate-500">Generated only from cached official source text; verify against the official record.</p></> : displayed.source_description ? <><p className="mt-2 text-sm font-bold">Official source description</p><p className="mt-2 whitespace-pre-line text-sm leading-7 text-slate-700">{displayed.source_description}</p></> : <MissingSource message={status === "retrieved" ? "The retrieved official record did not provide a study-purpose description." : "A source-grounded purpose description is not yet available. TrialMatch does not infer one from the title or conditions."} />}</section>
    {detail ? <div className={`mt-6 rounded-2xl border p-4 text-sm leading-6 ${detail.detail_status === "retrieved" ? "border-emerald-200 bg-emerald-50 text-emerald-950" : "border-amber-200 bg-amber-50 text-amber-950"}`}><p className="font-bold">{detail.detail_status === "retrieved" ? "Official detail available" : "Official detail unavailable"}</p><p>{detail.retrieval_message}</p></div> : null}
    <div className="mt-7 grid gap-3 sm:grid-cols-3"><InfoPanel title="Age eligibility" value={ageLabel(displayed.minimum_age, displayed.maximum_age, status)} helper="Published source range; not a recommendation." /><InfoPanel title="Phase" value={displayed.phases.length ? displayed.phases.map(formatPhase).join(", ") : "Not specified by source"} helper="Not Applicable is shown when supplied by the source." /><InfoPanel title="Registry sex field" value={sourceValue(displayed.sex, status)} helper="This registry field may not describe gender identity." /></div>
    <FacilitySection detail={detail} massachusetts={maLocations} other={otherLocations} status={status} />
    <section className="mt-8"><p className="text-xs font-bold uppercase tracking-[0.16em] text-accent">Published protocol</p><h3 className="mt-1 text-xl font-black">Eligibility requirements</h3>{detail?.detail_status === "retrieved" && detail.eligibility_criteria ? <div className="mt-4 whitespace-pre-line rounded-2xl border border-slate-200 bg-white p-5 text-sm leading-7 text-slate-700">{detail.eligibility_criteria}</div> : <MissingSource message={status === "retrieved" ? "Eligibility text was not specified in the retrieved official record." : "Eligibility text is not available from the indexed fields. Missing criteria are never treated as requirements met."} />}</section>
    <section className="mt-8"><p className="text-xs font-bold uppercase tracking-[0.16em] text-accent">Contact the study</p><h3 className="mt-1 text-xl font-black">Official contacts</h3>{detail?.detail_status === "retrieved" && detail.contacts.length ? <div className="mt-4 space-y-3">{detail.contacts.map((contact, index) => <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm" key={`${contact.name}-${contact.email}-${index}`}><p className="font-bold">{contact.name ?? "Study contact"}</p>{contact.facility ? <p className="mt-1 text-slate-500">{contact.facility}</p> : null}<div className="mt-2 flex flex-wrap gap-3">{contact.phone ? <a className="font-semibold text-accent hover:underline" href={`tel:${contact.phone}`}>{contact.phone}</a> : null}{contact.email ? <a className="font-semibold text-accent hover:underline" href={`mailto:${contact.email}`}>{contact.email}</a> : null}</div></div>)}</div> : <MissingSource message={status === "retrieved" ? "No contact details were provided in the retrieved official record. Use the official study page for updates." : "Contact details have not been retrieved."} />}</section>
    <section className="mt-8 rounded-2xl border border-indigo-200 bg-indigo-50 p-5"><p className="text-xs font-bold uppercase tracking-[0.16em] text-indigo-700">Preliminary screening support</p><h3 className="mt-2 font-black text-indigo-950">{detail && ["partial", "complete"].includes(detail.screening_coverage.status) ? "Structured requirement evidence is available" : "Detailed preliminary screening is not yet available"}</h3><p className="mt-2 text-sm leading-6 text-indigo-900">{detail?.screening_coverage.reason ?? "Open the official details to check current structured extraction coverage."}</p>{detail?.screening_coverage.status === "partial" ? <p className="mt-3 rounded-xl bg-white/70 p-3 text-xs leading-5 text-indigo-950"><strong>Partial coverage:</strong> passing currently structured checks cannot establish eligibility or a verified potential match.</p> : null}</section>
    <details className="mt-8 rounded-2xl border border-slate-200 bg-white p-4 text-sm"><summary className="cursor-pointer font-bold">Source and refresh details</summary><dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2"><div><dt className="text-slate-500">Official identifier</dt><dd className="mt-1 font-semibold">{summary.nct_id}</dd></div><div><dt className="text-slate-500">Last source update in TrialMatch</dt><dd className="mt-1 font-semibold">{formatTimestamp(displayed.retrieved_at)}</dd></div>{detail ? <><div><dt className="text-slate-500">Detail came from</dt><dd className="mt-1 font-semibold">{formatRetrievalSource(detail.retrieval_source)}</dd></div><div><dt className="text-slate-500">Latest retrieval attempt</dt><dd className="mt-1 font-semibold">{formatTimestamp(detail.detail_attempted_at)}</dd></div></> : null}</dl><div className="mt-4 flex flex-wrap gap-3"><a className="rounded-xl bg-accent px-4 py-2.5 font-bold text-white" href={summary.source_url} rel="noreferrer" target="_blank">View official ClinicalTrials.gov record ↗</a><button className="rounded-xl border border-slate-300 px-4 py-2.5 font-bold" disabled={loading} onClick={onRefresh} type="button">Refresh official data</button></div></details>
    </> : null}</div></section></div>;
}

function FacilitySection({detail, massachusetts, other, status}: {detail?: TrialDetail; massachusetts: TrialLocation[]; other: TrialLocation[]; status: string}) {
  if (detail?.detail_status !== "retrieved") return <section className="mt-8"><p className="text-xs font-bold uppercase tracking-[0.16em] text-accent">Access information</p><h3 className="mt-1 text-xl font-black">Study facilities</h3><MissingSource message={status === "retrieval_failed" ? "Facility details could not be retrieved. This does not mean the study has no locations." : "Official facility detail has not been retrieved, so no facility count can be claimed."} /></section>;
  return <section className="mt-8"><p className="text-xs font-bold uppercase tracking-[0.16em] text-accent">Access information</p><h3 className="mt-1 text-xl font-black">Massachusetts facilities</h3>{massachusetts.length ? <LocationList locations={massachusetts} /> : <MissingSource message="No Massachusetts facility was specified among the locations in this retrieved official record. This is not proof that no local option exists." />}<h3 className="mt-7 text-lg font-black">Other worldwide source facilities</h3>{other.length ? <LocationList locations={other} /> : <p className="mt-3 text-sm text-slate-600">No additional non-Massachusetts facilities were specified in the retrieved record.</p>}<p className="mt-3 text-xs leading-5 text-slate-500">Counts reflect locations returned in this official record, not verified availability, travel distance, or accessibility.</p></section>;
}

function LocationList({locations}: {locations: TrialLocation[]}) { return <div className="mt-4 space-y-3">{locations.map((site, index) => <div className="rounded-2xl border border-slate-200 bg-white p-4" key={`${site.facility}-${site.city}-${index}`}><div className="flex items-start justify-between gap-3"><p className="font-bold">{site.facility ?? "Facility name not specified"}</p>{site.recruiting_status ? <span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-bold uppercase ${statusClass(site.recruiting_status)}`}>{formatRegistryValue(site.recruiting_status)}</span> : <span className="text-xs text-slate-500">Recruiting status not specified</span>}</div><p className="mt-1 text-sm text-slate-600">{[site.city, site.state, site.postal_code, site.country].filter(Boolean).join(", ") || "Location not specified by source"}</p></div>)}</div>; }

function MatchResults({match, headingRef}: {match: MatchResponse; headingRef: React.RefObject<HTMLHeadingElement | null>}) { return <section aria-labelledby="results-heading" aria-live="polite" className="mt-14 border-t border-emerald-950/10 pt-12"><p className="text-xs font-bold uppercase tracking-[0.2em] text-accent">Transparent, evidence-linked preliminary results</p><h2 className="mt-2 scroll-mt-4 text-3xl font-black tracking-tight outline-none sm:text-4xl" id="results-heading" ref={headingRef} tabIndex={-1}>What the synthetic facts can—and cannot—show</h2><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">{match.disclaimer} Partial, stale, failed, or unattempted extraction remains unresolved even when individual requirements are met.</p><div className="mt-7 space-y-5">{match.results.map((result) => <article className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7" key={result.nct_id}><div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><p className="text-xs font-bold text-slate-400">{result.nct_id}</p><h3 className="mt-1 text-xl font-black sm:text-2xl">{result.title}</h3></div><span className={`w-fit rounded-full px-3 py-2 text-xs font-black ${screeningClass(result.screening_status)}`}>{screeningLabels[result.screening_status]}</span></div><div className={`mt-5 rounded-2xl border p-4 text-sm ${result.extraction_coverage.status === "complete" ? "border-emerald-200 bg-emerald-50 text-emerald-950" : "border-amber-200 bg-amber-50 text-amber-950"}`}><p className="font-bold">Source-requirement coverage: {coverageLabel(result.extraction_coverage.status)}</p><p className="mt-1 leading-6">{result.extraction_coverage.reason}</p><p className="mt-2 text-xs">{result.extraction_coverage.accounted_item_count} source items accounted for · {result.extraction_coverage.evaluable_criterion_count} deterministically evaluable · {result.extraction_coverage.uncovered_protocol_requirement_count} uncovered</p></div>{result.criteria.length ? <div className="mt-5 space-y-3">{result.criteria.map((criterion) => <details className="rounded-2xl border border-slate-200 p-4" key={criterion.criterion_id}><summary className="cursor-pointer list-none font-bold"><span className={`mr-2 inline-block rounded-full px-2.5 py-1 text-[11px] ${criterionClass(criterion.status)}`}>{criterionLabels[criterion.status]}</span><span className="text-sm">{criterion.original_text}</span></summary><p className="mt-3 text-sm leading-6 text-slate-700">{criterion.explanation}</p>{criterion.extraction_uncertainty ? <p className="mt-2 text-sm text-amber-800">Uncertainty: {criterion.extraction_uncertainty}</p> : null}<a className="mt-3 inline-block text-sm font-bold text-accent hover:underline" href={criterion.source_url} rel="noreferrer" target="_blank">Verify original evidence ↗</a></details>)}</div> : <p className="mt-5 rounded-2xl bg-slate-100 p-4 text-sm text-slate-700">No accepted current-source structured requirements are available. The result stays unresolved.</p>}{result.known_mismatches.length ? <ResultList title="Known requirements not met" values={result.known_mismatches} tone="red" /> : null}{result.unresolved_requirements.length ? <ResultList title="Information still unresolved" values={result.unresolved_requirements} tone="amber" /> : null}{result.missing_questions.length ? <ResultList title="Questions to confirm with the study team" values={result.missing_questions} tone="slate" /> : null}</article>)}</div><p className="mt-5 text-xs text-slate-500">Generated {formatTimestamp(match.generated_at)} from cached, validated structured evidence. TrialMatch does not automatically run paid eligibility extraction while browsing.</p></section>; }

function InfoItem({label, value}: {label: string; value: string}) { return <div><p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 font-semibold text-slate-700">{value}</p></div>; }
function InfoPanel({title, value, helper}: {title: string; value: string; helper: string}) { return <div className="rounded-2xl border border-slate-200 bg-white p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-400">{title}</p><p className="mt-2 font-black">{value}</p><p className="mt-2 text-xs leading-5 text-slate-500">{helper}</p></div>; }
function MissingSource({message}: {message: string}) { return <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-4 text-sm leading-6 text-slate-600">{message}</div>; }
function Alert({message, onRetry}: {message: string; onRetry: () => void}) { return <div className="mt-5 flex items-center justify-between gap-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert"><span>{message}</span><button className="shrink-0 rounded-lg bg-white px-3 py-2 font-bold ring-1 ring-red-200" onClick={onRetry} type="button">Try again</button></div>; }
function SearchSkeleton() { return <div className="space-y-4" role="status"><span className="sr-only">Loading studies</span>{[0, 1, 2].map((item) => <div className="animate-pulse rounded-3xl border border-slate-200 bg-white p-7" key={item}><div className="h-4 w-1/3 rounded bg-slate-200" /><div className="mt-4 h-8 w-4/5 rounded bg-slate-200" /><div className="mt-4 h-4 w-2/3 rounded bg-slate-100" /></div>)}</div>; }
function DetailSkeleton() { return <div className="animate-pulse" role="status"><span className="sr-only">Retrieving official study details</span><div className="h-5 w-1/3 rounded bg-slate-200" /><div className="mt-5 h-10 w-5/6 rounded bg-slate-200" /><div className="mt-3 h-5 w-2/3 rounded bg-slate-100" /><div className="mt-8 h-36 rounded-2xl bg-white" /></div>; }
function ResultList({title, values, tone}: {title: string; values: string[]; tone: "red" | "amber" | "slate"}) { const colors = {red: "border-red-200 bg-red-50 text-red-950", amber: "border-amber-200 bg-amber-50 text-amber-950", slate: "border-slate-200 bg-slate-50 text-slate-800"}; return <div className={`mt-4 rounded-2xl border p-4 text-sm ${colors[tone]}`}><h4 className="font-bold">{title}</h4><ul className="mt-2 list-disc space-y-1 pl-5">{values.map((value) => <li key={value}>{value}</li>)}</ul></div>; }

function sortTrials(trials: TrialSummary[], sort: SortOption): TrialSummary[] { const copy = [...trials]; if (sort === "title") return copy.sort((a, b) => a.title.localeCompare(b.title)); if (sort === "status") return copy.sort((a, b) => a.overall_status.localeCompare(b.overall_status) || a.title.localeCompare(b.title)); if (sort === "ma_sites") return copy.sort((a, b) => maSiteCount(b.locations) - maSiteCount(a.locations) || a.title.localeCompare(b.title)); return copy; }
function partitionLocations(locations: TrialLocation[]): {massachusetts: TrialLocation[]; other: TrialLocation[]} { const massachusetts: TrialLocation[] = []; const other: TrialLocation[] = []; locations.forEach((site) => (isMassachusetts(site) ? massachusetts : other).push(site)); return {massachusetts, other}; }
function isMassachusetts(site: TrialLocation): boolean { const state = site.state?.trim().toLocaleLowerCase(); return state === "massachusetts" || state === "ma"; }
function maSiteCount(locations: TrialLocation[]): number { return locations.filter(isMassachusetts).length; }
function facilityCountLabel(trial: TrialSummary, maOnly: boolean): string { if (trial.detail_status === "retrieved") { const count = maOnly ? maSiteCount(trial.locations) : trial.locations.length; return count ? `${count} source location${count === 1 ? "" : "s"}` : maOnly ? "None specified in MA" : "None specified by source"; } return trial.detail_status === "retrieval_failed" ? "Retrieval failed — retry available" : "Open details to retrieve"; }
function ageLabel(minimum: string | null, maximum: string | null, status: string): string { if (minimum && maximum) return `${minimum} to ${maximum}`; if (minimum) return `From ${minimum}; upper bound not specified`; if (maximum) return `Up to ${maximum}; lower bound not specified`; return status === "retrieved" ? "Not specified by source" : status === "retrieval_failed" ? "Retrieval failed" : "Not yet retrieved"; }
function sourceValue(value: string | null, status: string): string { return value ? formatRegistryValue(value) : status === "retrieved" ? "Not specified by source" : status === "retrieval_failed" ? "Retrieval failed" : "Not yet retrieved"; }
function errorMessage(payload: ApiError, fallback: string): string { const message = payload.error?.message ?? fallback; const detail = payload.error?.details?.map((item) => item.reason).filter(Boolean).join("; "); return detail ? `${message} ${detail}` : message; }
function formatTimestamp(value: string | null): string { if (!value) return "not available"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], {dateStyle: "medium", timeStyle: "short"}); }
function formatRegistryValue(value: string): string { return value.replaceAll("_", " ").toLocaleLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function formatPhase(value: string): string { if (value === "NA" || value === "NOT_APPLICABLE") return "Not Applicable"; return formatRegistryValue(value).replace("Phase", "Phase "); }
function formatRetrievalSource(value: TrialDetail["retrieval_source"]): string { return {local_database: "Local validated database", official_cache: "Validated official-response cache", official_api: "ClinicalTrials.gov API"}[value]; }
function statusClass(status: string): string { const normalized = status.toLocaleUpperCase(); if (["RECRUITING", "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING"].includes(normalized)) return "bg-emerald-100 text-emerald-900"; if (["NOT_YET_RECRUITING", "UNKNOWN"].includes(normalized)) return "bg-amber-100 text-amber-950"; if (["SUSPENDED", "TERMINATED", "WITHDRAWN"].includes(normalized)) return "bg-red-100 text-red-900"; return "bg-slate-100 text-slate-700"; }
function screeningClass(status: ScreeningStatus): string { return {potential_match: "bg-emerald-100 text-emerald-900", known_mismatch: "bg-red-100 text-red-900", unresolved: "bg-amber-100 text-amber-900"}[status]; }
function coverageLabel(status: ExtractionCoverageStatus): string { return {not_attempted: "not yet available", partial: "partial", complete: "independently verified complete protocol-item accounting", failed: "latest attempt failed safely", stale: "available only for an older source version"}[status]; }
function criterionClass(status: CriterionStatus): string { return {met: "bg-emerald-100 text-emerald-900", not_met: "bg-red-100 text-red-900", unknown: "bg-amber-100 text-amber-900"}[status]; }
