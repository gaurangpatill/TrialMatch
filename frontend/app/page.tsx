import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center px-6 py-16">
      <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-accent">
        Hackachusetts 2026 · H5
      </p>
      <h1 className="text-5xl font-bold tracking-tight text-ink">TrialMatch</h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-700">
        Source-grounded clinical trial discovery and research-access optimization.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link className="rounded-lg bg-accent px-5 py-3 font-semibold text-white" href="/patient">
          Open Patient Portal
        </Link>
        <span className="rounded-lg border border-slate-300 bg-white px-5 py-3 text-slate-600">
          Researcher Dashboard · independent workstream
        </span>
      </div>
      <aside className="mt-10 rounded-xl border border-slate-300 bg-white p-6 text-sm leading-6 text-slate-700">
        TrialMatch is a research prototype, not medical advice or a definitive eligibility
        determination. Patient demonstrations accept synthetic profiles only. Optimizer outputs are
        modeled outreach coverage, not observed enrollment.
      </aside>
    </main>
  );
}
