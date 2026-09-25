# Agents

Every agent (except the Supervisor, Critic and Report Writer, which are invoked through their own
protocol methods rather than the generic `run()`) subclasses `meridian.agents.base.BaseAgent` and is
executed through its template method `execute(task, state) -> AgentResult`:

1. Build a fresh `ToolContext` (evidence ledger, tool-call recorder) scoped to this run.
2. Call the agent's `run(task, state, ctx)` under `asyncio.timeout(settings.agent_timeout_seconds)`,
   catching every exception (timeout, `MeridianError`, or anything else) and turning it into a
   `TaskStatus.FAILED` output rather than propagating — a broken agent never crashes the graph.
3. Validate every returned `Finding` (`agents/validation.py`): a claim citing an evidence id that isn't in
   `state.evidence` or this task's own ledger has that id stripped; a `FACT`/`CALCULATED` finding left with
   no evidence ids or metric refs after stripping is marked `UNVERIFIED` rather than dropped.
4. Package the result — findings, sources, evidence, tool calls, LLM usage, `state_updates` (a dict merged
   into `ResearchState`, e.g. `{"metrics": ..., "financials": ...}`) — into an `AgentResult`.

Each specialist decides for itself, per call, whether to run **generative** (`self.generative`, true when
`ProviderRegistry.llm.generative` — i.e. an Anthropic key is configured) or **offline** (deterministic,
derives findings directly from tool output with no LLM call). Both paths call the *same* allowlisted tools
and are held to the *same* citation rules; the difference is only whether an LLM turns the gathered
evidence into prose, or a template does. **On this build, no generative call has ever reached the real
Anthropic API** — see the README's honesty section — so every finding actually produced during development
came from the offline path, exercised through `ScriptedLLMProvider` in tests.

Two LLM call shapes are available to agents (`agents/base.py`):

- **`llm_research`** — a bounded tool-use loop (`max_tool_steps`, default 6): the model chooses from its
  allowlisted tools, sees results wrapped in `<untrusted_evidence>` blocks, and eventually calls
  `submit_answer` with a schema-validated structured response. Used when the agent needs the model to
  *decide what to look up* (company, filings, news, macro, competitors).
- **`llm_structured`** — a single-shot structured generation over evidence/context the agent already
  gathered, no tool access at all. Used when the agent has already computed everything (financials,
  valuation) and only wants the model to narrate it, so the model has no way to introduce a number that
  didn't come from the engine.

## Supervisor

**Role:** resolves the company, plans the research, reviews results for gaps/conflicts, and builds the
task lists for revision and human feedback. Invoked via `resolve()` / `plan()` / `review()` /
`tasks_for_rework()` / `tasks_for_feedback()` — never `run()`/`execute()`.

- **`resolve`** — an explicit `request.ticker` wins; otherwise `agents/company_extraction.py:candidate_names`
  extracts candidates from the free-text query (ranking company names above bare uppercase tickers, and
  excluding ordinary research vocabulary like "AI", "ETF", "GDP", "CEO" from ever being read as a ticker —
  a real bug found by asking it to research NVIDIA and getting a report on C3.ai, whose ticker is `AI`) and
  tries `resolve_company` against each in turn.
- **`plan`** — always builds a **deterministic base plan** first: wave 1 is company, financials, filings,
  news, and macro *only if* `_macro_relevant(state)` is true (the company is a financial institution, or
  the request/focus-areas text mentions rates, inflation, the Fed, monetary policy, a yield curve, or a
  recession); wave 2 is competitors, valuation, risk; wave 3 is bull, bear. `depth=quick` skips macro and
  bull/bear entirely (recorded in `skipped_agents` with a reason); `depth=deep` adds `include_dcf: True` to
  the valuation task and a larger peer limit. Focus areas are appended to every task's objective and stored
  in its `instructions`. Only if a generative LLM is configured does the planner-tier model then get a
  chance to **refine** this plan — and the refinement is treated as untrusted advice, not authority:
  `_validate_refinement` rejects it outright if it proposes more than 10 tasks, names an unknown agent, or
  moves an agent to a different wave than its canonical one; a rejected or failed refinement silently keeps
  the deterministic plan.
- **`review`** — runs after every wave completes: any `FAILED` agent gets a rework task with a note
  quoting its error; a `COMPLETED` agent with zero findings (other than macro, where that's a valid
  outcome) is flagged as a conflict; `_metric_conflicts` parses figures out of every `CALCULATED` claim and
  checks them against `state.metrics`; `_peer_revenue_conflicts` checks the peer comparison's target-company
  revenue against the actual financial statements (5% tolerance). Bounded by `settings.max_supervisor_loops`
  (default 2) — once reached, `review` returns immediately with no further follow-up.
- **`tasks_for_rework`** / **`tasks_for_feedback`** — build new `ResearchTask`s with `revision = previous + 1`
  (so their fingerprint differs and dispatch never skips them as a duplicate), reusing the agent's original
  wave and objective plus an appended note. Feedback actions map to a fixed target agent: `DEEPEN_VALUATION`
  → valuation with `include_dcf: True`; `ADD_COMPETITOR` → competitors with `add_ticker`; `ADD_RISK_ANALYSIS`
  → risk; `RERUN_AGENT` → whichever agent the human named.

## Specialist agents

| Agent | Tool allowlist | Sections | LLM path | Offline path |
|---|---|---|---|---|
| **Company** | `resolve_company`, `get_company_profile`, `search_filings`, `get_filing_section`, `recall_research_memory` | Company Overview, Business Model | `llm_research`: model chooses tools to research business model, products, geography, competitors; must cite real evidence ids | Fetches the profile (one FACT finding on exchange/SIC), then runs three fixed retrieval queries (products/services, revenue & markets, customers & competition) against `search_filings`, deduplicating passages that answer more than one query so the same quote isn't repeated |
| **Financials** | `get_financial_statements`, `compute_financial_metrics`, `calculate_metric` | Financial Performance, Financial Trends, Key Ratios | `llm_structured` over a `computed_metrics` dict restricted to the relevant periods (latest, prior, TTM, current); every figure must be one of the given values and cite its exact dict key as a metric ref | Iterates fixed metric-key lists per section (performance: revenue, revenue_growth, gross_profit, operating_income, net_income, net_margin, free_cash_flow, fcf_margin; trends: margin YoY deltas + 3y/5y CAGR; ratios: current_ratio, debt_to_equity, roa, roe, plus market multiples) and emits one `CALCULATED` finding per populated metric, each citing that metric's own `ref` |
| **Filings** | `list_filings`, `index_filings`, `search_filings`, `get_filing_section`, `get_recent_8k_events` | Financial Performance, Key Risks, Recent Developments | `llm_research`: model queries MD&A, segments, risk factors, guidance, accounting changes, material events | Runs fixed retrieval queries per topic (MD&A → Financial Performance, segment disclosure → Financial Performance, risk factors → Key Risks, guidance/accounting changes/material events → Recent Developments) |
| **News** | `search_news`, `get_recent_8k_events` | Recent Developments | `llm_research` | Surfaces headlines as FACT-about-reporting and 8-K items as FACT; any read-through on what coverage *means* is INTERPRETATION, never stated as fact |
| **Macro** | `get_macro_indicators`, `search_filings` | Macro | `llm_research`, explicitly told that finding no material exposure and returning zero findings is a valid, expected result | Searches filings for interest-rate/inflation/tariff/currency language; **if no passage is found, returns zero findings and a summary saying so — not a failure.** When a passage is found, it's paired with a matching macro indicator by keyword (`_KEYWORD_INDICATORS`: "interest rate"/"treasury" → `ust_10y`/`ust_3m`/`fed_funds`; "inflation"/"cpi" → `cpi_yoy`) |
| **Competitors** | `find_peer_candidates`, `get_peer_snapshot`, `search_filings` | Industry & Competition | `llm_research`; may propose additional peers by ticker with a reason, each independently validated by resolution | Builds a `PeerComparison` from `get_peer_snapshot` for up to 5 peers (6 if `depth=deep`) |
| **Valuation** | `get_market_quote`, `compute_financial_metrics`, `calculate_metric`, `run_dcf`, `get_peer_snapshot` | Valuation | `llm_structured`, narrates already-computed multiples/DCF only — no tool access in the generative call itself, so it structurally cannot invent an assumption | Computes P/E, EV/EBITDA, EV/Sales, Price/Sales, Price/FCF against peer medians; derives DCF assumptions itself (see [`ARCHITECTURE.md`](ARCHITECTURE.md#the-determinism-boundary)) and runs `run_dcf` only when latest annual revenue and FCF are positive and shares outstanding are known, else records the specific skip reason |
| **Risk** | `search_filings`, `get_filing_section`, `calculate_metric` | Key Risks | `llm_research` | One finding per `RiskCategory` (financial, liquidity, debt, competitive, regulatory, operational, concentration, geopolitical, technology, valuation) where filing evidence exists, or a leverage/liquidity metric supports it |
| **Bull** | `lookup_evidence`, `search_filings` | Bull Case | Argues only from findings/evidence already in `state`, or newly retrieved via its two tools — never introduces an uncited claim | Same tool allowlist and constraint applies in both modes; the agent's whole job is argument, not new research |
| **Bear** | `lookup_evidence`, `search_filings` | Bear Case | Same as Bull, opposite thesis | Same |

A specialist that can't resolve a ticker at all (e.g. company resolution failed upstream) returns an
`AgentDraft` with an explanatory summary and zero findings rather than raising — the graph proceeds and the
supervisor's `review()` step will notice the empty output.

## Critic

The critic is invoked via `review(state) -> CriticResult`, never `run()`/`execute()`. It runs seven checks
in a fixed order, all deterministic and always executed regardless of LLM availability — these are the
safety net that has to work with zero API cost:

1. **`hallucinated_evidence`** — every evidence id a finding cites must exist in `state.evidence`. A
   citation to an id that was never actually retrieved is `HIGH` severity.
2. **`missing_fact_evidence`** — a `FACT` finding (not already `REJECTED`) with zero evidence ids is
   `MEDIUM` severity ("unsupported claim").
3. **`calculated_numbers`** — for every `CALCULATED` finding with metric refs, parse every number out of
   the claim text (`parse_figures_with_precision`, handling `$245.1B`, `245,122 million`, `15.7%`, negative
   signs) and check each parsed figure against the metric value its ref points to. A figure matches if it's
   within the display precision it was written at (`"0.09x"` legitimately rounds `0.0910831`) **or** within
   1% relative tolerance — the two conditions are combined, not substituted, so a correctly-rounded figure
   is never flagged while a genuinely different number still is. A mismatch is `HIGH` ("inconsistent
   figure").
4. **`stale_recent_developments`** — a Recent Developments finding citing a source published more than 400
   days ago is `MEDIUM` ("stale information").
5. **`near_duplicates`** — near-identical claims (`difflib.SequenceMatcher` ratio ≥ 0.9) made by *different*
   agents are flagged as duplication. A duplicate involving Bull or Bear is downgraded to `LOW` — restating
   an existing finding is literally their job — while a duplicate between two independent research agents
   stays `MEDIUM`.
6. **`contradictions`** — findings sharing a metric ref are checked for directional language (a fixed
   positive/negative word list: "grew"/"increased"/"rose" vs. "declined"/"fell"/"contracted"); if the same
   metric has both directions asserted across findings, every directional finding on it is flagged `HIGH`
   ("contradiction").
7. **`prevalidated_unverified`** — surfaces findings platform validation had already marked `UNVERIFIED`
   (citations stripped before the critic ever saw them) that none of the above checks independently caught,
   as `MEDIUM` ("missing citation").

Only after all seven run does an **optional LLM pass** (`critic`-tier model, only when generative) add
judgement the mechanical checks can't produce: unsupported claims and weak assumptions, reviewing each
agent's findings against its own cited evidence. Its output is filtered to only reference `finding_id`
values that actually exist in this run.

Every issue's severity determines the outcome for the finding and for the agent that produced it
(`_apply_issues`): a `HIGH` issue rejects the finding (`FindingStatus.REJECTED`); a `MEDIUM` issue marks it
`UNVERIFIED`; a finding that survives every check untouched (still `DRAFT`) is explicitly promoted to
`APPROVED` — `DRAFT` must never reach the report writer unreviewed. An agent with any unresolved `HIGH`
issue gets `Verdict.NEEDS_REVISION` (if `revision_round < max_revision_rounds`) or `Verdict.REJECTED`
(cap reached — its rejected findings are excluded, but the agent's other approved findings still appear).
The overall run verdict is `NEEDS_REVISION` while any agent needs revision and the cap isn't hit,
`REJECTED` if the cap is hit with unresolved `HIGH` issues remaining, else `APPROVED`.

## Report Writer

Invoked via `write(state) -> WriterResult`. Writes **only** from findings with `status == APPROVED`;
`UNVERIFIED` findings are confined to a separate Open Questions section, each visibly suffixed
`"(unverified)"`; `REJECTED` findings never reach the report at all. The Executive Summary is synthesized
separately from every other section — one best company-overview finding, up to four calculated financial
headlines, the strongest valuation/bull/bear points, and the top two risks — reusing each finding's own
`id`/evidence ids/metric refs rather than minting anything new, so it's exactly as traceable as the
findings it draws from.

In generative mode, the writer-tier model drafts each section's prose constrained to the findings supplied
in context and must end every factual/calculated sentence with a `[ev_xxx]` marker. Two independent checks
gate acceptance: every marker must resolve to a real evidence id in `state.evidence`
(`_MARKER_RE` extraction, checked against `known_ids`), and every number the model writes must match some
value in the metrics table within tolerance (`_numbers_not_grounded_in_metrics`). A draft that fails either
check gets one retry with the specific problem quoted back to the model (`max_section_retries = 2`); if it
still can't produce a clean section, that section falls back to deterministic composition — one paragraph
per finding, its own claim text plus its own evidence markers, so the fallback path is trivially citation-
correct by construction.
