# TrialMatch frontend

Shared Next.js, TypeScript, Tailwind CSS, and MapLibre GL JS application shell. It intentionally contains no patient or researcher feature engine on `main`.

```bash
npm ci
npm test
npm run typecheck
npm run build
```

Use `NEXT_PUBLIC_API_BASE_URL` from the local environment to reach the FastAPI service. Coordinate shared page/routing and API-client changes between workstream owners.
