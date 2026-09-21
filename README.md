# Study reconciliation workspace

A supervised public-record reconciliation demo for an AstraZeneca clinical intelligence analyst: inspect a registry change, prepare an evidence-backed verification request, and approve the saved draft. Not affiliated with or endorsed by AstraZeneca. The business need is a hypothesis, not a validated company requirement.

The monitoring foundation predates this exercise. This adaptation replaces the top tabs with a single review workspace, adds versioned request drafts and a shared-password demo gate, and prepares an isolated deployment.

## Local setup

Requires uv, Node 22 and pnpm. Monitoring additionally requires a PostgreSQL database; this repository does not provision one.

```bash
cp api/.env.example api/.env
cp web/.env.example web/.env.local
uv sync --project api
pnpm --dir web install
```

Set a strong `DEMO_PASSWORD` in `web/.env.local`. Generate a separate random `API_ACCESS_TOKEN` (for example with `openssl rand -hex 32`) and set the same value in `api/.env` and `web/.env.local`. These are server-only secrets; never use `NEXT_PUBLIC_` variables for them. Access fails closed when secrets are missing.

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

Open http://localhost:3000, sign in with the demo password, and load the synthetic scenario. The live watchlist is available through **Monitored studies**. Restart servers after changing their environment.

Without `DATABASE_URL`, monitoring returns an explicit 503; authenticated live study browsing remains available. Without `OPENAI_API_KEY`, evidence and manual drafting still work, but AI interpretation and request generation are unavailable. Missing AI output is never presented as an AI-generated draft.

## Deployment

### Isolated Accenture deployment

Configuration only: no hosted resources have been provisioned or changed by this adaptation. Leave the existing projects, database, domains, secrets, and `render.yaml` untouched. Use **new** Render and Vercel projects connected exclusively to `y2kr/tech-challenge-accenture`, not the previous challenge repository.

1. Verify the old projects still track their original repository. A new Blueprint filename does not disconnect an existing deployment trigger; do not push until repository connections have been checked.
2. Create a **new** Render Blueprint using `render.accenture.yaml`. It creates `accenture-reconciliation-api` and its own `accenture-reconciliation-db`; automatic API deployment is disabled. Supply a new `API_ACCESS_TOKEN` and, if wanted, `OPENAI_API_KEY`. Never reuse the old database URL. The API container runs migrations against this new database on startup.
3. Create a **new** Vercel project, root directory `web`. Set server-only `API_BASE_URL` to the new Render HTTPS URL, `API_ACCESS_TOKEN` to its matching token, and `DEMO_PASSWORD` to a strong demo password. No browser-facing API URL or CORS connection is needed: the web server proxies authenticated calls.
4. Keep Vercel deployment triggers tied only to this repository. Do not transfer domains, modify the old project's Git connection, or reuse its environment configuration.
5. After deploying, check `/health` on the new API; direct unauthenticated `/api/studies` must be denied. Open the new web URL in a private browser: sign-in must precede access to studies, drafts, and sync. Load the replay through the workspace.
6. Confirm the old URLs still serve the old application. Isolation is not verified until both hosting dashboards and deployed URLs have been checked.

Free hosting can sleep or have database lifetime limits; verify current provider terms before relying on it for the interview. Keep a local demo available. Separate projects may share provider accounts, but must not share services, database, or secrets.

## Environment variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `CORS_ORIGINS` | api | Optional comma-separated browser origins; unnecessary for the server-side proxy |
| `API_BASE_URL` | web server | Base URL of the isolated API; never exposed to browser code |
| `API_ACCESS_TOKEN` | api and web server | Matching server-to-server authentication secret |
| `DEMO_PASSWORD` | web server | Shared demo sign-in password |
| `DATABASE_URL` | api | Existing PostgreSQL database for snapshots/events; blank disables monitoring |
| `TEST_DATABASE_URL` | api `.env` or exported test environment | PostgreSQL test database; tests create and drop only a uniquely named isolated schema |
| `OPENAI_API_KEY` | api | Enables AI interpretation and request generation; blank leaves evidence and manual drafting usable |
| `OPENAI_MODEL` | api | Model used for that analysis; defaults to `gpt-4.1-mini` |

## Checks

```bash
./scripts/check
(cd api && uv run pytest)
node web/scripts/study-table.test.cjs
node --experimental-strip-types web/scripts/auth.test.mjs
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DISPOSABLE_DB pnpm --dir web test:e2e
```

Playwright applies migrations and writes demo data: use a dedicated disposable database, never an existing deployment database. It starts its own API and web servers with test-only access credentials.

Database tests skip explicitly when `TEST_DATABASE_URL` is unset. Set it separately before running pytest to exercise migrations, persistence, and the replay API. Tests never fall back to `DATABASE_URL`. Do not point it at production. The test role must be able to create schemas.

## Demonstration

Sign in and load the synthetic replay. Select the change in the queue; inspect exact before/after evidence separately from AI interpretation. Generate a verification request, or write one manually if AI is unavailable. Save, approve or reject the saved version, then copy or download it. Editing approved text requires fresh approval. The audit history preserves the request text and decision; **approved does not mean sent**. No external recipient or enterprise system is contacted.

The review queue is synthetic; the monitored-studies drawer is live. Repeating replay sync explains when no new change was created. Live change-monitoring endpoints remain available for development, but are not a UI mode.

For direct API access, export `API_ACCESS_TOKEN` securely and pass its bearer token with every request:

```bash
curl -H "Authorization: Bearer $API_ACCESS_TOKEN" -X POST 'http://localhost:8000/api/sync?mode=replay'
curl -H "Authorization: Bearer $API_ACCESS_TOKEN" 'http://localhost:8000/api/changes?source=replay'
```

Use an actual ID from `event_ids` or the inbox rather than assuming it is `1`. The first live observation establishes a baseline, not an event. Later live syncs compare against the stored current snapshot. The first replay creates five study-change events across Critical, High, and Medium severity; repeating it returns no new event IDs. Replay derives five labelled synthetic scenarios from a fixture, keeps them in a separate namespace even if an NCT ID matches a live study, and does not represent registry history.

`GET /api/changes` defaults to live events, ordered Critical → High → Medium → Low, then newest first. `source=replay` selects the replay inbox. `limit` defaults to 50 and is capped at 100. Detail responses include exact changed values, both normalised snapshots, hashes, retrieval timestamps, and source labels. Interactive API documentation is at `/docs`.

## Request and data flow

1. The browser calls same-origin Next.js endpoints using its demo session. The web server checks access and forwards allowed requests with a server-only token; FastAPI independently checks that token. `GET /api/studies` fetches the latest 50 AstraZeneca-led records from ClinicalTrials.gov. The browser never calls the registry directly.
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
- Database tests require `TEST_DATABASE_URL` and otherwise skip. They have been exercised against a disposable local PostgreSQL instance; this does not establish hosted deployment health.
- The inbox and detail UI cover the replay namespace only; live events are reachable through the API but have no UI controls.
- The shared-password gate is demo access control, not enterprise identity: there are no individual identities, roles, per-user audit attribution, or production retention policies. Do not use patient data or confidential information.
- AI prepares text from supplied evidence; it neither verifies the record against internal systems nor sends requests. Human review is required. Copying/downloading is an export, not proof of delivery.
- This is analyst decision support, not a prediction of safety, efficacy, approval, or commercial impact.
