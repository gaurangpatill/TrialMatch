"use client";

import Link from "next/link";
import {FormEvent, useEffect, useState} from "react";

import type {
  ApiError,
  CriterionStatus,
  MatchResponse,
  ScreeningStatus,
  TrialSearchResponse,
  TrialSummary,
} from "@/lib/clinical-contracts";

const statusLabels: Record<ScreeningStatus, string> = {
  potential_match: "Potential match",
  known_mismatch: "Known mismatch",
  unresolved: "Needs clarification",
};

const criterionLabels: Record<CriterionStatus, string> = {
  met: "Met",
  not_met: "Not met",
  unknown: "Unknown",
};

export function PatientPortal() {
  const [query, setQuery] = useState("");
  const [trials, setTrials] = useState<TrialSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [freshness, setFreshness] = useState<string | null>(null);
  const [age, setAge] = useState("");
  const [sex, setSex] = useState("");
  const [conditions, setConditions] = useState("");
  const [absentConditions, setAbsentConditions] = useState("");
  const [searching, setSearching] = useState(false);
  const [matching, setMatching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [match, setMatch] = useState<MatchResponse | null>(null);

  async function searchTrials(searchQuery: string) {
    setSearching(true);
    setError(null);
    setMatch(null);
    try {
      const parameters = new URLSearchParams({page: "1", page_size: "20"});
      if (searchQuery.trim()) parameters.set("query", searchQuery.trim());
      const response = await fetch(`/api/trials?${parameters}`, {cache: "no-store"});
      const payload = (await response.json()) as TrialSearchResponse | ApiError;
      if (!response.ok || !("items" in payload)) {
        throw new Error(errorMessage(payload as ApiError, "Trial search failed."));
      }
      setTrials(payload.items);
      setTotal(payload.pagination.total_items);
      setFreshness(payload.data_freshness.retrieved_at);
      setSelected((current) => current.filter((id) => payload.items.some((trial) => trial.nct_id === id)));
    } catch (reason) {
      setTrials([]);
      setTotal(0);
      setError(reason instanceof Error ? reason.message : "Trial search failed.");
    } finally {
      setSearching(false);
    }
  }

  useEffect(() => {
    void searchTrials("");
  }, []);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void searchTrials(query);
  }

  function toggleTrial(nctId: string) {
    setSelected((current) =>
      current.includes(nctId) ? current.filter((id) => id !== nctId) : [...current, nctId],
    );
  }

  async function runMatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected.length === 0) {
      setError("Select at least one trial before running preliminary screening.");
      return;
    }
    const ageValue = age.trim() ? Number(age) : null;
    if (ageValue !== null && (!Number.isFinite(ageValue) || ageValue < 0 || ageValue > 125)) {
      setError("Age must be between 0 and 125 years.");
      return;
    }
    setMatching(true);
    setError(null);
    try {
      const response = await fetch("/api/match", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({
          patient: {
            profile_id: `synthetic-browser-${Date.now()}`,
            synthetic: true,
            age_years: ageValue,
            sex: sex || null,
            conditions: commaList(conditions),
            medications: [],
            procedures: [],
            absent_conditions: commaList(absentConditions),
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
        throw new Error(errorMessage(payload as ApiError, "Preliminary matching failed."));
      }
      setMatch(payload);
    } catch (reason) {
      setMatch(null);
      setError(reason instanceof Error ? reason.message : "Preliminary matching failed.");
    } finally {
      setMatching(false);
    }
  }

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-emerald-950/10 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
          <Link className="text-xl font-bold tracking-tight" href="/">
            TrialMatch
          </Link>
          <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900">
            Research prototype · synthetic profiles only
          </span>
        </div>
      </header>

      <section className="mx-auto max-w-7xl px-5 py-10 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-accent">Patient Portal</p>
          <h1 className="mt-3 text-4xl font-bold tracking-tight sm:text-5xl">
            Find recruiting Massachusetts trials
          </h1>
          <p className="mt-5 text-lg leading-8 text-slate-700">
            Search official ClinicalTrials.gov records, select studies, and compare a synthetic
            profile with the limited criteria TrialMatch can evaluate deterministically.
          </p>
        </div>

        <div className="mt-8 rounded-2xl border border-amber-300 bg-amber-50 p-5 text-sm leading-6 text-amber-950">
          <strong>Preliminary screening only.</strong> This is not medical advice or confirmed
          eligibility. Missing information stays unknown, and study staff must review the complete,
          current protocol.
        </div>

        {error ? (
          <div className="mt-6 rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900" role="alert">
            {error}
          </div>
        ) : null}

        <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.75fr)]">
          <section aria-labelledby="trial-search-heading">
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="text-xl font-semibold" id="trial-search-heading">Search studies</h2>
              <form className="mt-4 flex gap-3" onSubmit={submitSearch}>
                <label className="sr-only" htmlFor="trial-query">Condition or study title</label>
                <input
                  className="min-w-0 flex-1 rounded-lg border border-slate-300 px-4 py-3 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                  id="trial-query"
                  maxLength={200}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Condition or study title"
                  type="search"
                  value={query}
                />
                <button
                  className="rounded-lg bg-accent px-5 py-3 font-semibold text-white disabled:cursor-wait disabled:opacity-60"
                  disabled={searching}
                  type="submit"
                >
                  {searching ? "Searching…" : "Search"}
                </button>
              </form>
              <div className="mt-3 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
                <span>{total.toLocaleString()} observed local records match this search</span>
                <span>Source freshness: {formatTimestamp(freshness)}</span>
              </div>
            </div>

            <div className="mt-5 space-y-4" aria-live="polite">
              {!searching && trials.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">
                  No locally ingested studies matched. Confirm that the backend ingestion command has
                  run, or try a broader search.
                </div>
              ) : null}
              {trials.map((trial) => {
                const isSelected = selected.includes(trial.nct_id);
                return (
                  <article
                    className={`rounded-2xl border bg-white p-5 shadow-sm transition ${
                      isSelected ? "border-accent ring-2 ring-accent/15" : "border-slate-200"
                    }`}
                    key={trial.nct_id}
                  >
                    <div className="flex items-start gap-4">
                      <input
                        aria-label={`Select ${trial.title}`}
                        checked={isSelected}
                        className="mt-1 h-5 w-5 accent-accent"
                        onChange={() => toggleTrial(trial.nct_id)}
                        type="checkbox"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide">
                          <span className="text-accent">{trial.nct_id}</span>
                          <span className="rounded-full bg-emerald-100 px-2 py-1 text-emerald-800">
                            {trial.overall_status}
                          </span>
                          {trial.phases.map((phase) => (
                            <span className="rounded-full bg-slate-100 px-2 py-1 text-slate-700" key={phase}>
                              {phase}
                            </span>
                          ))}
                        </div>
                        <h3 className="mt-3 text-lg font-semibold leading-7">{trial.title}</h3>
                        <p className="mt-2 text-sm text-slate-600">
                          {trial.conditions.length ? trial.conditions.join(" · ") : "Conditions not supplied"}
                        </p>
                        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500">
                          <span>Age: {trial.minimum_age ?? "not supplied"} – {trial.maximum_age ?? "not supplied"}</span>
                          <span>Sex: {trial.sex ?? "not supplied"}</span>
                          <span>{trial.locations.length} detailed location(s) cached</span>
                        </div>
                        <a
                          className="mt-4 inline-flex text-sm font-semibold text-accent underline-offset-4 hover:underline"
                          href={trial.source_url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          View official study record ↗
                        </a>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <aside>
            <form className="sticky top-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" onSubmit={runMatch}>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">Synthetic profile</p>
              <h2 className="mt-2 text-xl font-semibold">Preliminary screening</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {selected.length} trial{selected.length === 1 ? "" : "s"} selected. Blank fields remain unknown.
              </p>

              <label className="mt-5 block text-sm font-medium" htmlFor="age">Age in years</label>
              <input
                className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5"
                id="age"
                max="125"
                min="0"
                onChange={(event) => setAge(event.target.value)}
                placeholder="e.g. 42"
                step="0.1"
                type="number"
                value={age}
              />

              <label className="mt-4 block text-sm font-medium" htmlFor="sex">Sex eligibility field</label>
              <select
                className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5"
                id="sex"
                onChange={(event) => setSex(event.target.value)}
                value={sex}
              >
                <option value="">Unknown / not provided</option>
                <option value="female">Female</option>
                <option value="male">Male</option>
              </select>

              <label className="mt-4 block text-sm font-medium" htmlFor="conditions">Known conditions</label>
              <textarea
                className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5"
                id="conditions"
                onChange={(event) => setConditions(event.target.value)}
                placeholder="Comma-separated asserted conditions"
                rows={2}
                value={conditions}
              />

              <label className="mt-4 block text-sm font-medium" htmlFor="absent-conditions">Explicitly absent conditions</label>
              <textarea
                className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5"
                id="absent-conditions"
                onChange={(event) => setAbsentConditions(event.target.value)}
                placeholder="Only facts explicitly known to be absent"
                rows={2}
                value={absentConditions}
              />

              <button
                className="mt-5 w-full rounded-lg bg-ink px-4 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                disabled={matching || selected.length === 0}
                type="submit"
              >
                {matching ? "Evaluating…" : "Compare synthetic profile"}
              </button>
            </form>
          </aside>
        </div>

        {match ? (
          <section className="mt-12 border-t border-slate-300 pt-10" aria-labelledby="results-heading">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-accent">Evidence-linked results</p>
            <h2 className="mt-2 text-3xl font-bold" id="results-heading">Preliminary screening</h2>
            <p className="mt-3 text-sm text-slate-600">{match.disclaimer}</p>
            <div className="mt-6 space-y-5">
              {match.results.map((result) => (
                <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" key={result.nct_id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-accent">{result.nct_id}</p>
                      <h3 className="mt-1 text-xl font-semibold">{result.title}</h3>
                    </div>
                    <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${screeningClass(result.screening_status)}`}>
                      {statusLabels[result.screening_status]}
                    </span>
                  </div>

                  {result.criteria.length ? (
                    <div className="mt-5 space-y-3">
                      {result.criteria.map((criterion) => (
                        <details className="rounded-xl border border-slate-200 p-4" key={criterion.criterion_id}>
                          <summary className="cursor-pointer list-none font-medium">
                            <span className={`mr-2 inline-block rounded px-2 py-0.5 text-xs ${criterionClass(criterion.status)}`}>
                              {criterionLabels[criterion.status]}
                            </span>
                            {criterion.original_text}
                          </summary>
                          <p className="mt-3 text-sm leading-6 text-slate-700">{criterion.explanation}</p>
                          {criterion.extraction_uncertainty ? (
                            <p className="mt-2 text-sm text-amber-800">Uncertainty: {criterion.extraction_uncertainty}</p>
                          ) : null}
                          <a className="mt-3 inline-block text-sm font-semibold text-accent hover:underline" href={criterion.source_url} rel="noreferrer" target="_blank">
                            Verify against source ↗
                          </a>
                        </details>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-5 rounded-lg bg-slate-100 p-4 text-sm text-slate-700">
                      No validated structured criteria are cached for this study.
                    </p>
                  )}

                  {result.known_mismatches.length ? (
                    <ResultList title="Known mismatches" values={result.known_mismatches} tone="red" />
                  ) : null}
                  {result.unresolved_requirements.length ? (
                    <ResultList title="Unresolved requirements" values={result.unresolved_requirements} tone="amber" />
                  ) : null}
                  {result.missing_questions.length ? (
                    <ResultList title="Questions for study staff" values={result.missing_questions} tone="slate" />
                  ) : null}
                </article>
              ))}
            </div>
          </section>
        ) : null}
      </section>
    </main>
  );
}

function ResultList({title, values, tone}: {title: string; values: string[]; tone: "red" | "amber" | "slate"}) {
  const colors = {
    red: "border-red-200 bg-red-50 text-red-950",
    amber: "border-amber-200 bg-amber-50 text-amber-950",
    slate: "border-slate-200 bg-slate-50 text-slate-800",
  };
  return (
    <div className={`mt-4 rounded-xl border p-4 text-sm ${colors[tone]}`}>
      <h4 className="font-semibold">{title}</h4>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {values.map((value) => <li key={value}>{value}</li>)}
      </ul>
    </div>
  );
}

function commaList(value: string): string[] {
  return [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
}

function errorMessage(payload: ApiError, fallback: string): string {
  const message = payload.error?.message ?? fallback;
  const detail = payload.error?.details?.map((item) => item.reason).filter(Boolean).join("; ");
  return detail ? `${message} ${detail}` : message;
}

function formatTimestamp(value: string | null): string {
  if (!value) return "not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function screeningClass(status: ScreeningStatus): string {
  return {
    potential_match: "bg-emerald-100 text-emerald-900",
    known_mismatch: "bg-red-100 text-red-900",
    unresolved: "bg-amber-100 text-amber-900",
  }[status];
}

function criterionClass(status: CriterionStatus): string {
  return {
    met: "bg-emerald-100 text-emerald-900",
    not_met: "bg-red-100 text-red-900",
    unknown: "bg-amber-100 text-amber-900",
  }[status];
}
