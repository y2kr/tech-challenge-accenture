# Clinical Trial Monitoring Workspace

Decision-support workspace that monitors AstraZeneca-led studies through the official ClinicalTrials.gov v2 API. Not affiliated with or endorsed by AstraZeneca.

## Local setup

Requires uv, Node 22 and pnpm. Stage 2 additionally requires an existing PostgreSQL database; this repository does not provision one.

```bash
cp api/.env.example api/.env
cp web/.env.example web/.env.local
uv sync --project api
pnpm --dir web install

(cd api && uv run fastapi dev src/monitor/main.py)
(cd web && pnpm dev)
```

Run the API and web commands in separate terminals from the repository root. Open http://localhost:3000. The browser watchlist remains live; Stage 2 change detection is available through the API, not a new UI.

For monitoring, set `DATABASE_URL` in `api/.env` to your existing database, then apply the schema before starting the API:

```bash
(cd api && uv run alembic upgrade head)
```

Use a PostgreSQL URL such as `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`. Never commit credentials. Without `DATABASE_URL`, the watchlist and health endpoint still work; monitoring endpoints return an explicit 503.

## Environment variables

| Variable | Where | Purpose |
| --- | --- | --- |
| `CORS_ORIGINS` | api | Comma-separated browser origins allowed to call the API |
| `NEXT_PUBLIC_API_BASE_URL` | web | Base URL of the API |
| `DATABASE_URL` | api | Existing PostgreSQL database for snapshots/events; blank disables monitoring |
| `TEST_DATABASE_URL` | api `.env` or exported test environment | PostgreSQL test database; tests create and drop only a uniquely named isolated schema |

## Checks

```bash
./scripts/check
(cd api && uv run pytest)
node web/scripts/study-table.test.cjs
```

Database tests skip explicitly when `TEST_DATABASE_URL` is unset. Set it separately before running pytest to exercise migrations, persistence, and the replay API. Tests never fall back to `DATABASE_URL`. Do not point it at production. The test role must be able to create schemas.

## Stage 2 demonstration

With the migration applied and API running:

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
- No Stage 3 inbox/detail UI, AI explanation, follow-up actions, review decisions, or audit workflow is implemented. `review_status` remains `unreviewed`.
- No authentication or infrastructure was added. The manual sync endpoint is intended for this local prototype, not unrestricted public production use.
- This is analyst decision support, not a prediction of safety, efficacy, approval, or commercial impact.
