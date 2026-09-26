# Meridian

Meridian is a multi-agent equity research platform. Point it at a company and a research question —
*"Analyse NVIDIA with attention to AI infrastructure growth, margins and valuation"* — and it resolves the
company, plans the research, dispatches specialist agents in parallel waves, pulls evidence from SEC EDGAR
filings, market data and news, computes every financial metric in deterministic Python (never in the
language model), challenges its own conclusions through a critic loop, optionally pauses for a human
approval gate, and writes a citation-backed report where every fact traces back to a real source.

It is a decision-support tool, not investment advice. Every report separates **Fact**, **Calculated** and
**Interpretation** content and carries a disclaimer.

## Why this exists

Most "AI research agent" demos either hard-code the output or let a language model quietly invent numbers.
Meridian is an attempt to build the boring, correct version of that idea: an LLM is good at reading a
messy 10-K and being told what a number means, and bad at arithmetic and bad at knowing when it's making
something up. So arithmetic never touches the model — a pure-Python financial engine computes every ratio,
margin, multiple and DCF from parsed XBRL figures — and every claim an agent writes down must resolve to
an evidence id it actually retrieved or a metric reference the engine actually computed. A critic agent
then re-checks all of that mechanically (not just by asking the model to grade itself) before a report
writer is allowed to compose prose from it.

The interesting engineering is less "can an LLM write a report" and more: what does it take to make a
multi-agent system's *claims* trustworthy — typed evidence chains, a deterministic calculation boundary,
citation validation that rejects fabricated markers, and a critic that parses figures out of English
sentences and checks them against a metrics table with the same precision they were written at.

## Status, honestly

This is a from-scratch build, verified end to end in **offline deterministic mode**. Read this before
anything else:

- **No Anthropic API key was available during development.** The generative LLM path (Claude-driven
  planning, tool-use research loops, critic judgement, report prose) is fully implemented and covered by
  unit tests using a scripted fake LLM client, but it has **never been exercised against the real Anthropic
  API**. Whether the prompts, tool schemas and retry logic hold up against the live model is unverified.
- **Postgres and the Docker stack are verified.** Both images build, all four containers come up healthy,
  the Alembic migration runs on container start, and a full research run completes in the containerised
  stack with results persisted (a Microsoft run: 60s, 13 sections, 933 sources, 11,553 evidence records).
  The DB integration tests and the pgvector store tests pass against a real pgvector instance, and skip
  cleanly when one is not reachable.
- **Runs execute in the API process, capped at four at once.** A fifth concurrent request is refused
  with `429 too_many_active_runs` rather than queued. Measured `/health` latency: ~60ms idle, p95 264ms
  beside one cold run, p95 792ms (worst observed 2.2s) with four cold runs saturating the cap. The real
  ceiling is not latency but durability — in-flight runs live in an in-memory checkpointer and do not
  survive a restart. A separate worker process with a persistent checkpointer is the fix, and this build
  does not have one.
- **Without an API key, the system runs in deterministic offline mode**: every specialist agent has a
  non-generative code path that derives findings directly from tool output, so a full run produces real
  figures and real citations, but mechanical, template-driven prose rather than model-written analysis.
- This is **not production-ready and has not been deployed anywhere**. It is a from-scratch reference build.

None of that is hidden in the code, either — see the git history for the actual bugs found while making
each part work (wrong fiscal year from SEC XBRL tagging, a wrong company resolved from a plain-English
query, Stooq silently switching to an anti-bot page, and others), documented in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) and the commit messages themselves.

## Screenshots

All captured from real runs against live SEC EDGAR data, in offline LLM mode (no API key), running in
Docker. Nothing here is mocked or staged.

**The report** — every paragraph is tagged `FACT`, `CALCULATED` or `INTERPRETATION` and carries a
citation marker. The figures come from the deterministic financial engine, not the model.

![Report section with Fact/Calculated badges and citation markers](docs/images/report.png)

**The citation drawer** — clicking any marker opens the exact evidence behind the claim: source,
publisher, filing section and the quoted passage.

![Citation drawer showing the evidence behind a claim](docs/images/citation-drawer.png)

**A run in flight** — waves of specialist agents with per-agent status and a live event feed over SSE.

![Live run view with the agent wave graph and event feed](docs/images/live-run.png)

**The human approval gate** — the run pauses before the report is written so a human can inspect the
plan, the retrieved sources and the preliminary findings, then approve or demand more work.

![Approval panel with plan, sources and preliminary findings](docs/images/review-panel.png)

**The trace** — per-agent tool calls, durations and token/cost accounting.

![Trace view with agent runs, usage and stage timings](docs/images/trace.png)

<details>
<summary>Dashboard, request form and sources view</summary>

![Dashboard listing recent runs](docs/images/dashboard.png)

![New research request form](docs/images/new-research.png)

![Sources view listing every retrieved document](docs/images/sources.png)

</details>

## Architecture at a glance

```mermaid
flowchart LR
    subgraph Client
        FE["Next.js 15 frontend<br/>(App Router, TS, Tailwind, Recharts)"]
    end

    subgraph Backend["FastAPI backend"]
        API["/api/v1 routers + SSE stream"]
        Runner["ResearchRunner<br/>(asyncio run manager)"]
        Graph["LangGraph StateGraph"]
        Agents["13 agents<br/>(supervisor, 8 specialists, bull, bear, critic, writer)"]
        Tools["19 typed tools<br/>(allowlisted per agent)"]
        Providers["Provider fallback chains"]
        RAG["RAG pipeline<br/>(parse / section / chunk / embed / retrieve)"]
    end

    subgraph Data["Storage"]
        PG[("Postgres 16 + pgvector")]
        Redis[("Redis cache + rate limiter")]
    end

    subgraph External["External data (keyless by default)"]
        SEC["SEC EDGAR<br/>(filings, XBRL, peers)"]
        Yahoo["Yahoo Finance chart<br/>(Stooq fallback)"]
        GDELT["GDELT news"]
        Treasury["US Treasury yields"]
        Anthropic["Anthropic API<br/>(optional)"]
    end

    FE -- "server-side proxy injects X-API-Key" --> API
    API --> Runner --> Graph --> Agents
    Agents --> Tools --> Providers
    Agents --> RAG
    Providers --> SEC & Yahoo & GDELT & Treasury
    Agents -. "generative mode only" .-> Anthropic
    RAG --> PG
    Providers -. "cache" .-> Redis
    Runner --> PG
    API -. "rate limiting" .-> Redis
```

Full component breakdown, the typed shared state, the determinism boundary and the request lifecycle are
in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## The multi-agent workflow

```mermaid
flowchart TD
    START([START]) --> intake
    intake --> plan
    plan --> dispatch

    dispatch -- "Send one WorkerInput per pending task in the current wave" --> specialists["specialist worker nodes<br/>(company, financials, filings, news, macro /<br/>competitors, valuation, risk / bull, bear)"]
    specialists --> advance_wave
    dispatch -. "nothing runnable" .-> advance_wave

    advance_wave -- "more pending tasks" --> dispatch
    advance_wave -- "critic asked for rework" --> critic
    advance_wave -- "changes_requested from human review" --> write_report
    advance_wave -- "otherwise" --> supervisor_review

    supervisor_review -- "gap/conflict follow-up tasks<br/>(bounded by max_supervisor_loops)" --> dispatch
    supervisor_review -- "no follow-up" --> critic

    critic -- "high-severity issues & rounds < max_revision_rounds" --> revise
    critic -- "require_approval & not yet approved" --> human_review
    critic -- "otherwise" --> write_report
    revise --> dispatch

    human_review{{"interrupt(): pause for human approval"}}
    human_review -- "feedback -> extra tasks<br/>(deepen valuation / add competitor / add risk / rerun agent)" --> dispatch
    human_review -- "approved" --> write_report

    write_report --> finalize --> END([END])
```

Every worker node feeds the single fan-in point `advance_wave`; a conditional edge there (`route_after_wave`
in `graph/routing.py`) is what makes the same collector serve four different loops — initial waves,
supervisor follow-up, critic revision and post-approval extra work — without threading extra state through
the tasks themselves. Safeguards: `max_revision_rounds=2`, `max_supervisor_loops=2`, a LangGraph recursion
limit, per-task fingerprint dedup (a task is never dispatched twice for the same fingerprint), a per-agent
timeout, and a failed specialist is recorded without aborting the run. Details in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/AGENTS.md`](docs/AGENTS.md).

## The 13 agents

| Agent | Wave | Responsibility | Tools (allowlist) | Output |
|---|---|---|---|---|
| Supervisor | plan / review | Resolves the company, builds a deterministic wave plan (optionally LLM-refined), reviews results for gaps and conflicts, builds revision/feedback tasks | `resolve_company` | `ResearchPlan`, follow-up tasks, conflict list |
| Company | 1 | Business model, products, geography, competitive position from the 10-K and profile | `resolve_company`, `get_company_profile`, `search_filings`, `get_filing_section`, `recall_research_memory` | Findings → Company Overview, Business Model |
| Financials | 1 | Financial performance, trends and ratios, strictly from engine-computed metrics | `get_financial_statements`, `compute_financial_metrics`, `calculate_metric` | `FinancialMetrics` + findings → Financial Performance/Trends, Key Ratios |
| Filings | 1 | MD&A, segments, risk factors, guidance, accounting changes and material events from 10-K/10-Q/8-K | `list_filings`, `index_filings`, `search_filings`, `get_filing_section`, `get_recent_8k_events` | Findings → Financial Performance, Key Risks, Recent Developments |
| News | 1 | Recent news and 8-K events, keeping factual reporting separate from interpretation | `search_news`, `get_recent_8k_events` | Findings → Recent Developments |
| Macro | 1 (conditional) | Only asserts a rates/inflation/trade/FX link when the company's own filing text supports it | `get_macro_indicators`, `search_filings` | Findings → Macro, or zero findings with a stated reason |
| Competitors | 2 | Peer identification and comparison on growth/margins | `find_peer_candidates`, `get_peer_snapshot`, `search_filings` | `PeerComparison` + findings → Industry & Competition |
| Valuation | 2 | Trading multiples vs. peers and an optional DCF whose assumptions are always derived deterministically | `get_market_quote`, `compute_financial_metrics`, `calculate_metric`, `run_dcf`, `get_peer_snapshot` | `ValuationResult` + findings → Valuation |
| Risk | 2 | Categorised risks (financial, liquidity, debt, competitive, regulatory, operational, concentration, geopolitical, technology, valuation), each tied to filing evidence or a metric | `search_filings`, `get_filing_section`, `calculate_metric` | Findings → Key Risks |
| Bull | 3 | Strongest evidence-based bull case, argued only from findings/evidence already in state | `lookup_evidence`, `search_filings` | Findings → Bull Case |
| Bear | 3 | Strongest evidence-based bear case, same constraint | `lookup_evidence`, `search_filings` | Findings → Bear Case |
| Critic | review | Deterministic integrity checks (hallucinated evidence, unsupported facts, figures vs. metrics table, stale developments, duplicates, contradictions) + optional LLM judgement pass | none | `CriticReview`, per-finding status changes |
| Report Writer | final | Composes the report strictly from approved/unverified findings; rejects any `[ev_xxx]` marker that doesn't resolve | none | `ResearchReport` |

Depth (`quick` / `standard` / `deep`) and focus areas adjust the plan: `quick` drops macro and bull/bear;
`deep` adds a DCF and more peers. Full detail — including the critic's exact checks and how the supervisor
decides to skip an agent — is in [`docs/AGENTS.md`](docs/AGENTS.md).

## Technology stack

| Layer | Choice |
|---|---|
| Agent framework | LangGraph 1.2 `StateGraph`, `Send` fan-out, `interrupt` for human-in-the-loop |
| LLM | Anthropic SDK 1.x behind an `LLMProvider` interface, with a deterministic `OfflineLLMProvider` and a `ScriptedLLMProvider` for tests |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 (async) + Alembic |
| Database | PostgreSQL 16 with pgvector (documents/chunks, evidence, findings, runs, telemetry) |
| Cache | Redis with typed TTL policy, in-memory fallback |
| Embeddings | fastembed (`BAAI/bge-small-en-v1.5`), deterministic hashing fallback |
| Frontend | Next.js 15 App Router, TypeScript (strict), Tailwind CSS, Recharts |
| Observability | structlog JSON logs, DB-persisted runs/tool calls/usage, optional OpenTelemetry + LangSmith |
| Testing | pytest (`asyncio_mode=auto`), respx for HTTP mocking, vitest for the frontend |

## Getting started

### Prerequisites

Python 3.12, Node.js 20+, and (optionally, for the full stack) Docker Desktop and/or a local Postgres 16
with the `pgvector` extension and Redis 7.

### Windows (PowerShell)

```powershell
scripts\setup.ps1          # backend venv + pip install, npm install, copy .env files
scripts\docker-up.ps1 -DepsOnly   # start Postgres + Redis only (or point DATABASE_URL/REDIS_URL at your own)
scripts\migrate.ps1        # alembic upgrade head
scripts\dev.ps1            # runs backend (uvicorn --reload) and frontend (next dev) together
```

Every `scripts\*.ps1` file is a line-for-line PowerShell equivalent of the matching `make` target — see the
comments at the top of each script.

### Linux / macOS (Makefile)

```bash
make setup          # backend venv + pip install, npm install, copy .env files
make docker-up-deps # docker compose up -d db redis
make migrate        # alembic upgrade head
make dev            # uvicorn --reload + next dev together
```

`make help` lists every target (`test`, `lint`, `format`, `docker-up`, `eval`).

### Running without Postgres/Redis at all

The backend starts and serves a full offline research run with **no database and no Redis**: `/health`
reports `database: false, redis: false` and the API still works — state lives in-process, and the RAG
pipeline falls back to an in-memory vector store. This is the mode verified on the development machine:

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn meridian.api.app:create_app --factory --port 8000   # Windows
# .venv/bin/python -m uvicorn meridian.api.app:create_app --factory --port 8000          # Linux/macOS
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0","database":false,"redis":false,"auth_required":false}
```

### Environment variables

Copy `.env.example` to `.env`; every value is optional. Key groups (see the file for the full, commented
list):

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `LLM_PROVIDER=auto` | With a key set, `auto` uses Anthropic; without one, deterministic offline mode |
| `MODEL_PLANNER` / `MODEL_WORKER` / `MODEL_CRITIC` / `MODEL_WRITER`, `EFFORT_*` | Per-tier model and reasoning-effort selection |
| `DATABASE_URL`, `REDIS_URL` | Postgres / Redis connection strings |
| `DATA_MODE=auto` | `live` (network only), `snapshot` (recorded fixtures only), `auto` (live with snapshot fallback) |
| `SEC_USER_AGENT` | Required format for SEC EDGAR: `"Company/Name email@domain"` |
| `FMP_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `FRED_API_KEY` | Optional paid/free-tier providers; adapters activate automatically when a key is present |
| `API_KEY`, `RATE_LIMIT_PER_MINUTE` | API auth and rate limiting (open API when `API_KEY` is unset — local dev only) |
| `REQUIRE_APPROVAL_DEFAULT`, `MAX_REVISION_ROUNDS` | Workflow safeguards |

The frontend has its own `frontend/.env.local` (`MERIDIAN_API_BASE_URL`, `MERIDIAN_API_KEY`) — these are
server-side only; the browser never sees the API key.

## Docker

`docker-compose.yml` at the repo root defines `db` (pgvector/pgvector:pg16) and `redis` (redis:7-alpine) as
always-on datastore services, plus `backend` and `frontend` app services behind a `full` profile.
`docker/backend.Dockerfile` and `docker/frontend.Dockerfile` are multi-stage, non-root, healthchecked
images (`docker/backend-entrypoint.sh` waits for Postgres and runs `alembic upgrade head` before starting
uvicorn).

```bash
make docker-up-deps   # just Postgres + Redis, for local dev against the venv
make docker-up        # full stack, built and started
```

Verified end to end: both images build, all four containers report healthy, migrations apply on start,
the app containers run as non-root, and a full research run completes through the containerised stack
with its results persisted to Postgres.

## Testing

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/unit -q
```

**578 passed, 1 skipped, 9 deselected** on this machine (deselected = `@pytest.mark.live` tests that hit
real external APIs, excluded by the default `-m ''not live''`; the one skip is
`test_pgvector_store.py`, which needs a reachable Postgres). Integration tests under
`backend/tests/integration` are marked `@pytest.mark.integration` and skip cleanly without Postgres/Redis.

Two end-to-end tests in `backend/tests/e2e/` drive the real graph against live SEC data: one asserts that
"Analyse Microsoft" yields a report whose every citation resolves, the other that a fabricated company
fails rather than resolving to something plausible.

```bash
.venv/Scripts/python.exe -m pytest tests/e2e -m integration -q     # ~60s, needs network
```

Linting and type-checking, both wired into CI and `make lint`:

```bash
.venv/Scripts/python.exe -m ruff check src tests && .venv/Scripts/python.exe -m mypy src
```

Frontend: `npm run lint && npx tsc --noEmit && npm run test && npm run build` inside `frontend/`.

## Evaluation

```bash
python evals/run_eval.py              # seven benchmark cases, ~1 min each
python evals/run_eval.py --snapshot   # recorded data only, no network
```

Seven cases covering different fiscal calendars, a bank whose margins must be absent rather than wrong, a
natural-language request, quick depth, a company that does not exist, and a prompt-injection harness.
Latest run: **7/7 passed**, with citation coverage, source correctness and calculation accuracy all at
1.000 and zero unsupported claims in the finished reports.

Those scores measure the deterministic pipeline -- retrieval, calculation, citation integrity and the
critic's rules -- not the quality of generated prose, because offline mode generates none. Methodology,
full results and honest limitations: [`docs/EVALUATION.md`](docs/EVALUATION.md); scorecards land in
`evals/results/`.

## Security

Prompt-injection defence (retrieved text only ever enters the model inside delimited, clearly-labelled
`<untrusted_evidence>` blocks, never the system role), an outbound SSRF allowlist, per-agent tool
allowlists, parameterised SQL only, a server-side API-key proxy so the browser never holds a credential,
Redis-backed rate limiting, and a strict frontend CSP. Full writeup, including residual risks, in
[`docs/SECURITY.md`](docs/SECURITY.md).

## Limitations

- The generative LLM path has unit-test coverage against a scripted fake client but **has never been run
  against the real Anthropic API** — no key was available. Prompt shapes, tool-call parsing and refusal
  handling are unverified against the real model.
- **Runs execute in the API process, capped at four concurrent** (`MAX_CONCURRENT_RUNS`); a fifth is
  refused with `429`, not queued. Measured `/health`: ~60ms idle, p95 264ms alongside one cold run,
  p95 792ms and a worst observed 2.2s with the cap saturated. The binding limit is durability, not
  latency: the LangGraph checkpointer is in-memory, so a restart loses any run still in flight.
- Without an LLM key, report prose is mechanically composed from finding claims — correct and cited, but
  not fluent analysis.
- Stooq (the documented keyless price source) currently returns an anti-bot challenge page instead of CSV;
  the platform works around this with an unofficial Yahoo Finance chart endpoint as the primary keyless
  source, which could change or disappear without notice.
- SEC's `browse-edgar` SIC Atom feed has a long-standing server bug that renders company names as literal
  `ARRAY(0x...)` strings; peer discovery falls back to ranking XBRL revenue frames when this happens.
- GDELT enforces an informal, undocumented rate limit and no key-based alternative is wired in by default.
- **Filing text is extracted from HTML, and extraction is imperfect.** Page-break navigation, section
  headings and flattened tables are filtered out of quoted claims, and chunk boundaries are
  sentence-aligned, so 0.3% of indexed chunks now open mid-sentence (it was 60.5% when the overlap
  carried whole words instead). What survives is page headers and table captions that read like prose;
  the cited evidence always holds the full passage.
- This is a reference build for one machine, not a deployed or load-tested service.

## Roadmap

- Verify the generative LLM path against the real Anthropic API and tune prompts based on real model output.
- A persistent LangGraph checkpointer plus a worker process, so an in-flight run survives a restart and
  concurrency is bounded by workers rather than by one event loop.
- A keyed market-data provider (FMP/Polygon) as the default primary, with Yahoo/Stooq as fallback only.
- Extract filing tables as structured rows rather than flattening them into text, so the figures in them
  become citable metrics instead of being filtered out of claims.
