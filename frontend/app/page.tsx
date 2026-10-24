export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center px-6 py-16">
      <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-accent">
        Hackachusetts 2026 · H5
      </p>
      <h1 className="text-5xl font-bold tracking-tight text-ink">TrialMatch</h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-700">
        Shared application scaffold for source-grounded clinical trial discovery and
        research-access optimization.
      </p>
      <aside className="mt-10 rounded-xl border border-slate-300 bg-white p-6 text-sm leading-6 text-slate-700">
        This prototype is not medical advice or a definitive eligibility determination.
        Feature work is intentionally isolated to the clinical and geographic branches.
      </aside>
    </main>
  );
}
