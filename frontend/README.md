# TrialMatch frontend

Integrated Next.js, TypeScript, Tailwind CSS, and MapLibre GL JS patient and researcher experience.

```bash
npm ci
npm test
npm run typecheck
npm run build
```

For local development, `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` permits direct browser requests to FastAPI. This value is browser-visible and must never contain secrets.

For Vercel production, leave `NEXT_PUBLIC_API_BASE_URL` unset and set the server-only `TRIALMATCH_API_BASE_URL` to the Railway origin. Existing clinical route handlers proxy patient requests, and `next.config.ts` rewrites geography/optimizer requests through the same Vercel origin. This avoids permissive production CORS and keeps backend configuration out of the client bundle.

See [`../docs/deployment.md`](../docs/deployment.md) and [`../docs/release-checklist.md`](../docs/release-checklist.md). Coordinate changes to shared routing/API contracts between frontend and backend owners.
