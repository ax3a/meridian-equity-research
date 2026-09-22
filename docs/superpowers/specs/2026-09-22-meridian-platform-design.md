# Meridian — Multi-Agent Equity Research Platform: Design Spec

Date: 2026-09-22 · Status: Approved

## 1. Goal

Given a request such as *"Analyse NVIDIA with attention to AI infrastructure growth, margins and valuation"*,
the platform resolves the company, plans the research, dispatches specialist agents, gathers evidence from
official and public sources, computes metrics deterministically, challenges its own conclusions through a
critic loop, optionally pauses for human review, and writes a citation-backed research report.

It is a decision-support tool, not financial advice. Every report distinguishes FACT, CALCULATED and
INTERPRETATION content and carries a disclaimer.

## 2. Decisions

| Area | Decision | Rationale |
|---|---|---|
| Agent framework | LangGraph `StateGraph`, `Send` fan-out, `interrupt` for HITL | Real graph with loops, routing, checkpoints |
| LLM | `LLMProvider` interface; `AnthropicProvider` + deterministic `OfflineProvider` + `ScriptedProvider` (tests) | Full pipeline runs with zero API cost |
| Filings / fundamentals | SEC EDGAR (submissions, companyfacts XBRL, frames, documents) | Official, free, keyless |
| Prices | Stooq CSV (keyless); optional Polygon/Alpha Vantage | Provider-swappable |
| News | GDELT DOC 2.0 + SEC 8-K events; optional Finnhub | Keyless default |
| Macro | US Treasury Fiscal Data API; optional FRED | Keyless default |
| Vector store | pgvector in the main Postgres | One fewer service |
| Embeddings | fastembed `BAAI/bge-small-en-v1.5` (local); hashing embedder fallback | Free, offline |
| DB | PostgreSQL 16, SQLAlchemy 2 async, Alembic | Required |
| Cache | Redis with typed TTL policy; in-memory fallback | Freshness-aware |
| API | FastAPI, `/api/v1`, SSE progress stream | Async, typed |
| Runner | In-process asyncio run manager | Single-node; Celery documented as scale path |
| Frontend | Next.js 15 App Router, TypeScript, Tailwind, Recharts | Required |
| Observability | structlog JSON + DB-persisted runs/tool calls/usage; optional OTel + LangSmith | Works with no external service |

## 3. Package layout

```
backend/src/meridian/
  core/             config (pydantic-settings), logging, errors, ids, clock
  schemas/          state, research, citations, findings, financials, report, api
  financial_engine/ ratios, growth, valuation, dcf, statements (pure functions)
  providers/        base protocols; llm/, sec/, market/, news/, macro/, http client, registry
  rag/              parsing, sectioning, chunking, embeddings, store, retriever, pipeline
  tools/            typed tools with allowlists and call recording
  agents/           base + 13 agents
  graph/            state reducers, nodes, routing, builder, runner
  db/               models, session, repositories, migrations (alembic)
  cache/            redis cache + memory fallback + TTL policy
  memory/           user preferences, research memory with freshness
  observability/    tracing, usage/cost accounting, event bus
  security/         prompt-injection scanner, evidence wrapping, SSRF guard, sanitisation
  api/              app factory, deps, middleware, v1 routers, SSE
```

## 4. Agents

| Agent | Wave | Inputs | Output |
|---|---|---|---|
| Supervisor | plan/review | request, prefs, data availability | `ResearchPlan`, follow-up tasks, conflict notes |
| Company | 1 | profile, 10-K Item 1 | findings |
| Financials | 1 | XBRL statements | `FinancialMetrics` (engine) + findings |
| Filings | 1 | 10-K/10-Q/8-K via RAG | findings (MD&A, risk factors, segments, events) |
| News | 1 | GDELT + 8-K | findings separated FACT vs INTERPRETATION |
| Macro | 1 (conditional) | Treasury rates, sector sensitivity | findings or `skipped: not material` |
| Competitors | 2 | SIC peers + frames revenue | `PeerComparison` + findings |
| Valuation | 2 | price, shares, metrics, peers | `ValuationResult` (multiples, optional DCF) + findings |
| Risk | 2 | all wave-1 outputs | categorised risks, each with evidence |
| Bull / Bear | 3 | approved-so-far findings | thesis with cited points |
| Critic | review | all outputs + metrics | `CriticReview` with per-section verdicts |
| Report Writer | final | approved findings only | `ResearchReport` |

## 5. Graph

```
intake → plan → dispatch(wave n) → [agents in parallel] → collect → (more waves? dispatch)
      → supervisor_review → (gaps? dispatch) → critic → (rework & rounds<max? revise→critic)
      → human_review (interrupt if enabled) → (extra work? dispatch) → write_report → finalize
```

Safeguards: `max_revision_rounds=2`, `max_supervisor_loops=2`, LangGraph `recursion_limit`, task
fingerprint dedup, per-agent timeout, retries with exponential backoff for providers and LLM calls,
fallback provider chains, failed agents recorded without crashing the run.

## 6. Citations

`Source(id, kind, title, url, publisher, published_at, retrieved_at, provider, is_snapshot, metadata)`
`Evidence(id, source_id, locator{section,page,xbrl_concept,period}, text)`
`Finding(id, agent, section, claim, kind, evidence_ids, metric_refs, confidence, status)`

Validation: evidence ids must exist in the run's evidence store; FACT findings require ≥1 evidence id;
CALCULATED findings require ≥1 metric ref; unverifiable findings become `status=UNVERIFIED` and render
visibly marked.

## 7. Security

Retrieved content is data: wrapped in `<untrusted_evidence>` blocks in user-role content after a
system-level instruction; injection scanner flags directive patterns; tool allowlists per agent;
outbound HTTP restricted to an allowlisted host set (SSRF guard); HTML sanitised before parsing;
API key auth, Redis rate limiting, parameterised SQL only, CSP headers on frontend, no secrets in code.

## 8. Testing & evaluation

pytest unit (engine, parsers, schemas, routing, tools, security), integration (API, DB, RAG, graph),
agent tests (routing selection, citation presence, critic rejection of planted claims), E2E offline run
for Microsoft. Eval suite with benchmark queries producing a JSON + Markdown scorecard.
