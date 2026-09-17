# tech-challenge-1609

Clinical-trial monitoring workspace. `plan.md` is the build specification; `CONTEXT.md` is the domain glossary.

## Layout

- `api/` — FastAPI service, uv project, Python 3.14. Package `src/monitor/`: `main.py` (HTTP routes, CORS, error responses), `clinicaltrials.py` (ClinicalTrials.gov client and normalisation), `settings.py` (env config)
- `web/` — Next.js App Router, TypeScript strict, pnpm. `src/app/` pages, `src/api/` generated schema and typed fetch, `src/lib/` display labels, `src/components/ui/` shadcn components
- `scripts/check` — the single definition of "passes" (pre-commit: ruff, hygiene, no-comments, eslint, prettier, tsc)

## Commands

- Install: `uv sync --project api` and `pnpm --dir web install`
- Run API: `cd api && uv run fastapi dev src/monitor/main.py` (port 8000; needs `api/.env`, see `.env.example`)
- Run web: `cd web && pnpm dev` (port 3000; needs `web/.env.local`, see `.env.example`)
- Check: `./scripts/check` or `./scripts/check <files>`
- Test: `cd api && uv run pytest`
- Regenerate API contract after changing API models or routes: `cd web && pnpm gen:api` (CI fails on drift)

CI (`.github/workflows/ci.yml`) runs `./scripts/check`, pytest, and the contract drift check.
