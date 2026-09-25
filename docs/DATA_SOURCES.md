# Data sources

Meridian is built so a developer with no API keys can run the whole system. Every capability has a free,
keyless default; paid providers are optional adapters that activate when a key is present and report
themselves unavailable when it is not.

## Provider matrix

| Capability | Default (keyless) | Optional adapters | Notes |
| --- | --- | --- | --- |
| Company lookup | SEC `company_tickers.json` | FMP | Ticker, name and CIK for every SEC filer |
| Company profile | SEC submissions API | — | SIC code, exchange, fiscal year end, former names |
| Financial statements | **SEC XBRL company facts** | FMP, Alpha Vantage | The authoritative source: figures as filed |
| Filings and text | SEC EDGAR submissions + Archives | — | 10-K, 10-Q, 8-K with item codes |
| Peer universe | SEC SIC lookup + XBRL frames | Finnhub | Dynamically selected, never hardcoded |
| Prices | Yahoo chart endpoint | Polygon, Alpha Vantage, FMP, Finnhub | See "Stooq" below |
| News | GDELT DOC 2.0 | Finnhub | Headlines are evidence of reporting, not of fact |
| Macro | US Treasury par yield curve | FRED | Only used when materially relevant |
| Embeddings | fastembed (local), hashing fallback | — | No embedding API cost |
| LLM | Deterministic offline mode | Anthropic | See `docs/ARCHITECTURE.md` |

Chains are ordered: the keyless source is tried first, and an adapter that is not configured is skipped
with a warning rather than failing the run. `ProviderResult.provider` always names the provider that
actually answered, so attribution in the report stays honest.

## Why SEC EDGAR is the primary source

Core financial figures come from XBRL company facts rather than a data vendor, because those are the
numbers the company itself filed, each one traceable to an accession number and a reporting period. Every
value carries an evidence record naming the concept, period and filing, which is what makes the report's
citation chain possible.

## Real-world quirks discovered

These are not theoretical. Each one was found by running against live data, and each is handled in code.

**Fiscal years describe the filing, not the period.** In company facts, every fact carries `fy`/`fp`
describing the *report it appeared in*. A FY2026 10-K restates FY2025 and FY2024 comparatives tagged
`fy=2026`. Grouping by that field silently shifted every year: Microsoft's FY2022 revenue was labelled
FY2024, corrupting every growth rate and multiple downstream. Periods are now pooled across line items,
labelled from the filing that first reported them, and reconciled against the most recent period, so any
fiscal calendar works (Microsoft ends in June, Apple in September, NVIDIA in late January).

**Filers change XBRL concepts mid-history.** NVIDIA tags recent years under `Revenues` and older years
under `RevenueFromContractWithCustomerExcludingAssessedTax`. Choosing one concept per company returned no
revenue at all for the years that matter, so the concept is chosen per period, with chain order breaking
ties and a later filing winning for restatements.

**A 10-K tags two balance sheets with the same period.** Instant facts appear for both the current and
prior year end under one accession. Keying by the actual period end rather than the label avoids the
collision.

**Stooq no longer serves CSV to scripts.** It returns an anti-bot challenge page with HTTP 200. The
market chain now tries Yahoo's chart endpoint first — an unofficial, undocumented endpoint, which is a
deliberate trade-off for keyless operation and documented as a limitation. Configure Polygon or Alpha
Vantage for a supported path.

**GDELT rate-limits aggressively.** Roughly one request every five seconds; exceeding it returns HTTP
429. The client throttles that host specifically, and a 429 falls back to recorded data rather than
failing the run.

**SEC's browse-EDGAR Atom feed has a templating bug.** Company names render as the literal string
`ARRAY(0x...)`. CIKs are parsed from the feed and cross-referenced against `company_tickers.json` to
recover names and tickers.

**Warrants and shells share an issuer's SIC code.** Peer selection by SIC returned tickers like `AISPW`
and zero-revenue shells as comparables; those are filtered out.

## Snapshot and demo mode

`scripts/record_snapshots.py` records real provider responses to `backend/snapshots/` (about 3 MB for
three companies). With `DATA_MODE=snapshot` the platform serves only recorded data, so the system runs
with no network at all; with `DATA_MODE=auto` it uses live data and falls back to a snapshot when a
provider fails.

Recorded data is never presented as live. Sources carry `is_snapshot` and the date recorded, the report
carries `uses_snapshot_data`, and the UI shows a badge. Data that is stale is labelled stale rather than
quietly shown as current.

## Rate limits and etiquette

SEC requires a descriptive `User-Agent` with contact details — set `SEC_USER_AGENT` in `.env` before
running against live data. Requests are throttled per host (8 req/s for SEC, well inside their 10 req/s
guidance), filings are cached permanently because they never change, and prices are cached for 15
minutes.
