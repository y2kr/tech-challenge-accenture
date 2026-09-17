# Clinical Trial Monitoring Workspace

Decision-support workspace that monitors AstraZeneca-led studies through the official ClinicalTrials.gov v2 API. Not affiliated with or endorsed by AstraZeneca.

## Local setup

Requires uv, Node 22 and pnpm. Monitoring additionally requires a PostgreSQL database; this repository does not provision one.

```bash
cp api/.env.example api/.env
cp web/.env.example web/.env.local
uv sync --project api
pnpm --dir web install
```

Set `DATABASE_URL` in `api/.env` to a PostgreSQL URL such as `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`. Never commit credentials. A throwaway local database is enough:

```bash
podman run -d --name monitor-pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=monitor \
  docker.io/library/postgres:17
```

That container matches `postgresql+psycopg://postgres:dev@localhost:5432/monitor`. Apply the schema, then start both servers in separate terminals from the repository root:

```bash
(cd api && uv run alembic upgrade head)

(cd api && uv run fastapi dev src/monitor/main.py)
(cd web && pnpm dev)
```

Open http://localhost:3000 for the watchlist and http://localhost:3000/changes for the change inbox. Restart the API after editing `api/.env`; settings are read at startup.

Without `DATABASE_URL`, the watchlist and health endpoint still work, but every monitoring endpoint returns an explicit 503 and the change inbox renders "Monitoring database is not configured." Without `OPENAI_API_KEY`, the inbox and detail views work and the AI analysis section reports that it is unavailable.

## Deployment

The API runs as a container on Render; the web app runs on Vercel. `render.yaml` is a Render Blueprint that declares the service, a free PostgreSQL instance, the health check, and `alembic upgrade head` as the pre-deploy command. Push the repository first; both hosts build from GitHub.

1. Render → New → Blueprint → select this repository. When prompted, supply `OPENAI_API_KEY` and set `CORS_ORIGINS` to a placeholder such as `https://example.vercel.app`.
2. Vercel → import the same repository → **root directory `web`** → set `NEXT_PUBLIC_API_BASE_URL` to the Render URL, without a trailing slash.
3. Set `CORS_ORIGINS` on Render to the Vercel domain from step 2 and redeploy. Until this matches exactly, browser calls fail while `curl` still succeeds.
4. Seed the demonstration: `curl -X POST 'https://YOUR-API.onrender.com/api/sync?mode=replay'`.

Render's free PostgreSQL expires after 30 days; for a longer-lived deployment, create a Neon database instead and set `DATABASE_URL` manually. Hosted connection strings begin `postgresql://`, which SQLAlchemy reads as psycopg2; settings rewrite that prefix to `postgresql+psycopg://` automatically, so paste the string as issued. Free instances sleep when idle, so the first request after a pause is slow.

## Environment variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `CORS_ORIGINS` | api | Comma-separated browser origins allowed to call the API |
| `NEXT_PUBLIC_API_BASE_URL` | web | Base URL of the API |
| `DATABASE_URL` | api | Existing PostgreSQL database for snapshots/events; blank disables monitoring |
| `TEST_DATABASE_URL` | api `.env` or exported test environment | PostgreSQL test database; tests create and drop only a uniquely named isolated schema |
| `OPENAI_API_KEY` | api | Enables AI analysis on change detail; blank disables it without breaking the page |
| `OPENAI_MODEL` | api | Model used for that analysis; defaults to `gpt-4.1-mini` |

## Checks

```bash
./scripts/check
(cd api && uv run pytest)
node web/scripts/study-table.test.cjs
```

Database tests skip explicitly when `TEST_DATABASE_URL` is unset. Set it separately before running pytest to exercise migrations, persistence, and the replay API. Tests never fall back to `DATABASE_URL`. Do not point it at production. The test role must be able to create schemas.

## Demonstration

In the browser, with both servers running: open the change inbox, press **Load replay event** to seed the synthetic recruiting-to-terminated event, open it for the evidence diff and AI analysis, approve or reject a follow-up action, and read the result in the audit timeline. The inbox reads the replay namespace; live events are available through the API.

The same flow through the API:

```bash
curl -X POST 'http://localhost:8000/api/sync?mode=live'
curl -X POST 'http://localhost:8000/api/sync?mode=replay'
curl -X POST 'http://localhost:8000/api/sync?mode=replay'
curl 'http://localhost:8000/api/changes?source=replay'
curl 'http://localhost:8000/api/changes/1'
```

Use an actual ID from `event_ids` or the inbox rather than assuming it is `1`. The first live observation establishes a baseline, not an event. Later live syncs compare against the stored current snapshot. The first replay creates one Critical event; repeating it returns no new event IDs. Replay uses two explicitly synthetic fixtures, is labelled in every response, and lives in a separate namespace even if an NCT ID matches a live study. It is not historical registry evidence.

`GET /api/changes` defaults to live events, ordered Critical → High → Medium → Low, then newest first. `source=replay` selects the replay inbox. `limit` defaults to 50 and is capped at 100. Detail responses include exact changed values, both normalised snapshots, hashes, retrieval timestamps, and source labels. Interactive API documentation is at `/docs`.

## Request and data flow

1. The Next.js watchlist requests `GET /api/studies`; FastAPI fetches the latest 50 AstraZeneca-led records from ClinicalTrials.gov. The browser never calls the registry directly.
2. A manual `POST /api/sync` fetches the same source data, validates it, and extracts only the monitored fields. Invalid studies are logged, skipped, and counted.
3. Canonicalisation sorts/deduplicates unordered collections and sorts JSON object keys. It preserves text and date precision. SHA-256 fingerprints that normalised content; timestamps and unmonitored metadata cannot create false change events.
4. A PostgreSQL transaction locks each study, stores a unique snapshot per content hash, and compares against an explicit current-snapshot pointer. A first observation sets the baseline; an unchanged observation creates no event. A genuine return to an earlier state reuses its snapshot but still creates a new transition event.
5. Semantic comparison records exact before/after values only for monitored fields. Deterministic rules choose the highest applicable severity. Snapshots, the event, and the current pointer commit together or roll back together.
6. Inbox/detail endpoints read persisted evidence without fetching the registry or calling an LLM. The original raw JSON is retained in storage for traceability; it is not the basis of the semantic diff.

## Demo severity rules

- **Critical:** Recruiting → Terminated/Withdrawn/Suspended, or reason stopped added/changed.
- **High:** Interventions or primary outcomes changed; primary completion delayed by at least **30 days**; enrolment reduced by at least **20%** from a positive known count.
- **Medium:** Country or location added/removed.
- **Low:** Other monitored changes, including phase, eligibility, completion date, and smaller count/date changes.

Thresholds are named constants covered by tests, not clinical conclusions. Partial dates preserve their precision and do not trigger the exact-day delay rule. Location identity uses facility, city, state, country, and postal code; contact details, coordinates, and site recruitment status are not monitored. Intervention descriptions and outcome measure/description/time frame are monitored; arm-group mappings are not.

## Scope and limitations

- The watchlist covers AstraZeneca as lead sponsor (`query.lead`), not collaborators, and only the 50 most recently updated studies; there is no pagination or scheduler.
- Only observed transitions are known. There is no claim to registry history, and omitted studies are not treated as deletions.
- Snapshot retrieval time is the first observation of that unique content. A later return to the same content reuses that snapshot; event creation time records the later transition.
- PostgreSQL migrations, transactional persistence, and DB-backed replay acceptance remain unverified until the gated tests run with `TEST_DATABASE_URL`. Pure rules and API boundary tests do not substitute for them.
- The inbox and detail UI cover the replay namespace only; live events are reachable through the API but have no UI controls.
- No authentication or infrastructure was added. The manual sync endpoint is intended for this local prototype, not unrestricted public production use.
- This is analyst decision support, not a prediction of safety, efficacy, approval, or commercial impact.
