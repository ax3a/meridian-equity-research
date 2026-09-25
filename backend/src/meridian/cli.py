"""Meridian command-line interface (`meridian` entry point, declared in `pyproject.toml`).

Three commands:
  meridian research "Analyse Microsoft" [--ticker MSFT] [--depth standard] [--json]
  meridian serve [--host 0.0.0.0] [--port 8000] [--reload]
  meridian record-snapshots [--ticker MSFT ...] [--years 5]

`research` and `record-snapshots` build the same runtime the API server does (`api.wiring.build_runtime`)
but always in-memory (`use_database=False`): a one-shot CLI invocation has no need for cross-run
persistence, and this keeps the command usable with zero setup, Postgres or not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap
from typing import Any

from meridian.api.wiring import build_runtime
from meridian.core.config import get_settings
from meridian.core.errors import MeridianError
from meridian.core.logging import configure_logging, get_logger
from meridian.observability.tracing import configure_tracing
from meridian.schemas.enums import RunStatus
from meridian.schemas.events import ProgressEvent
from meridian.schemas.report import ResearchReport
from meridian.schemas.research import HumanFeedback, ResearchRequest

log = get_logger(__name__)


def _print(line: str = "") -> None:
    print(line)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meridian", description="Meridian multi-agent equity research platform")
    sub = parser.add_subparsers(dest="command", required=True)

    research_p = sub.add_parser("research", help="run a research session and print live progress + the final report")
    research_p.add_argument("query", help='free-text research request, e.g. "Analyse Microsoft"')
    research_p.add_argument("--ticker", default=None, help="ticker hint, e.g. MSFT")
    research_p.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")
    research_p.add_argument("--json", action="store_true", help="emit machine-readable JSON lines instead of prose")
    research_p.add_argument(
        "--no-auto-approve",
        action="store_true",
        help="prompt on the terminal at the approval checkpoint instead of auto-approving",
    )

    serve_p = sub.add_parser("serve", help="run the FastAPI server with uvicorn")
    serve_p.add_argument("--host", default="0.0.0.0")  # noqa: S104 - a dev server binding to all interfaces is the point
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true")

    snap_p = sub.add_parser(
        "record-snapshots", help="fetch live data for one or more tickers and record it for offline/snapshot mode"
    )
    snap_p.add_argument("--ticker", action="append", dest="tickers", default=None, help="repeatable; defaults to MSFT")
    snap_p.add_argument("--years", type=int, default=5, help="years of financial statements to fetch")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "research":
        asyncio.run(_cmd_research(args))
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "record-snapshots":
        asyncio.run(_cmd_record_snapshots(args))
    else:  # pragma: no cover - argparse enforces `required=True` above
        parser.print_help()
        sys.exit(2)


# ---------------------------------------------------------------------------
# meridian research
# ---------------------------------------------------------------------------


def _format_event(event: ProgressEvent) -> str:
    agent = f"[{event.agent.value}] " if event.agent else ""
    return f"{event.at:%H:%M:%S} #{event.seq:<4} {agent}{event.message}"


def _prompt_approval(runtime: Any, session_id: str) -> None:
    _print()
    answer = input("  Awaiting approval - approve this run? [Y/n/<comment>]: ").strip()
    if answer == "" or answer.lower() in ("y", "yes"):
        runtime.runner.resume(session_id, [HumanFeedback(action="approve")])
        return
    if answer.lower() in ("n", "no"):
        runtime.runner.resume(session_id, [HumanFeedback(action="comment", comment="rejected from the CLI")])
        return
    runtime.runner.resume(session_id, [HumanFeedback(action="comment", comment=answer)])


def _format_report(report: ResearchReport) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(report.title)
    lines.append(
        f"{report.company.name} ({report.company.ticker}) - generated {report.generated_at:%Y-%m-%d %H:%M UTC}"
    )
    lines.append(
        f"llm_mode={report.llm_mode}  data_mode={report.data_mode}  uses_snapshot_data={report.uses_snapshot_data}"
    )
    lines.append("=" * 78)
    for section in report.sections:
        lines.append("")
        lines.append(f"## {section.title}")
        for para in section.paragraphs:
            marker = "  [unverified]" if para.unverified else ""
            lines.append(textwrap.fill(para.text, width=100, initial_indent="  ", subsequent_indent="  ") + marker)
    if report.key_metrics:
        lines.append("")
        lines.append("## Key metrics")
        for row in report.key_metrics:
            values = ", ".join(f"{period}={value}" for period, value in row.values.items())
            lines.append(f"  {row.label} [{row.unit}]: {values}")
    if report.valuation is not None:
        v = report.valuation
        lines.append("")
        lines.append("## Valuation")
        lines.append(f"  price={v.price}  market_cap={v.market_cap}  enterprise_value={v.enterprise_value}")
        for m in v.multiples:
            lines.append(f"  {m.label}: {m.value} (peer median {m.peer_median})")
        if v.dcf is not None:
            lines.append(f"  DCF value/share={v.dcf.value_per_share:.2f}  upside={v.dcf.upside_pct}")
    lines.append("")
    lines.append(f"{report.unverified_claims} unverified claim(s) across {report.critic_rounds} critic round(s).")
    lines.append("")
    lines.append(report.disclaimer)
    return "\n".join(lines)


async def _cmd_research(args: argparse.Namespace) -> None:
    configure_logging()
    settings = get_settings()
    configure_tracing(settings)
    runtime = await build_runtime(settings, use_database=False)
    try:
        request = ResearchRequest(query=args.query, ticker=args.ticker, depth=args.depth)
        if not args.json:
            _print(
                f'Starting research: "{request.query}" '
                f"(depth={request.depth}, llm_mode={settings.llm_mode}, data_mode={settings.data_mode})"
            )
            _print()

        session_id = await runtime.runner.start(request)
        auto_approve = not args.no_auto_approve

        async for event in runtime.runner.subscribe(session_id, after_seq=0):
            _print(event.model_dump_json() if args.json else _format_event(event))
            if event.type.value == "awaiting_approval":
                state = await runtime.runner.status(session_id)
                if state is not None and state.status == RunStatus.AWAITING_APPROVAL:
                    if auto_approve:
                        if not args.json:
                            _print("  -> auto-approving (pass --no-auto-approve to review interactively)")
                        runtime.runner.resume(session_id, [HumanFeedback(action="approve")])
                    else:
                        _prompt_approval(runtime, session_id)

        state = await runtime.runner.status(session_id)
        if state is None:
            _print("error: run state vanished unexpectedly")
            sys.exit(1)

        if args.json:
            _print(
                json.dumps(
                    {
                        "session_id": session_id,
                        "status": state.status.value,
                        "report": state.report.model_dump(mode="json") if state.report else None,
                        "errors": [e.model_dump(mode="json") for e in state.errors],
                    }
                )
            )
        else:
            _print()
            if state.status == RunStatus.COMPLETED and state.report is not None:
                _print(_format_report(state.report))
            elif state.status == RunStatus.FAILED:
                _print(f"Run FAILED: {state.errors[-1].message if state.errors else 'unknown error'}")
            elif state.status == RunStatus.CANCELLED:
                _print("Run cancelled.")
            else:
                _print(f"Run ended in status '{state.status.value}' without a report.")

        if state.status == RunStatus.FAILED:
            sys.exit(1)
    finally:
        await runtime.aclose()


# ---------------------------------------------------------------------------
# meridian serve
# ---------------------------------------------------------------------------


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("meridian.api.app:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


# ---------------------------------------------------------------------------
# meridian record-snapshots
# ---------------------------------------------------------------------------


async def _cmd_record_snapshots(args: argparse.Namespace) -> None:
    configure_logging()
    settings = get_settings()
    tickers = args.tickers or ["MSFT"]

    from meridian.cache.base import build_cache
    from meridian.core.http import HttpClient
    from meridian.providers.factory import build_providers
    from meridian.providers.snapshots import SnapshotStore

    record_settings = settings.model_copy(
        update={"data_mode": "live" if settings.data_mode == "snapshot" else settings.data_mode}
    )
    cache = build_cache(record_settings.redis_url)
    snapshots = SnapshotStore(record_settings.snapshot_dir)
    http = HttpClient(record_settings, cache, snapshots, record_snapshots=True)
    providers = build_providers(record_settings, http=http, cache=cache)

    _print(f"Recording snapshots into {record_settings.snapshot_dir} (data_mode={record_settings.data_mode})")
    try:
        for ticker in tickers:
            _print(f"\n{ticker}:")
            try:
                company = await providers.directory.resolve(ticker)
            except MeridianError as exc:
                _print(f"  resolve: FAILED ({exc.message})")
                continue
            _print(f"  resolve: {company.name} (CIK {company.cik})")

            steps: list[tuple[str, Any]] = [
                ("profile", lambda c=company: providers.directory.profile(c)),
                ("statements", lambda c=company: providers.fundamentals.get_statements(c, years=args.years)),
                ("filings", lambda c=company: providers.filings.list_filings(c)),
                ("quote", lambda c=company: providers.market.get_quote(c.ticker)),
                ("news", lambda c=company: providers.news.search_news(c)),
                ("macro", lambda: providers.macro.get_indicators()),
                ("peers", lambda c=company: providers.peers.candidate_peers(c)),
            ]
            for label, step in steps:
                try:
                    await step()
                    _print(f"  {label}: recorded")
                except MeridianError as exc:
                    _print(f"  {label}: FAILED ({exc.message})")
                except Exception as exc:  # a recording pass should keep going even on a surprising failure
                    log.exception("record_snapshot_step_failed", ticker=ticker, step=label)
                    _print(f"  {label}: FAILED ({type(exc).__name__}: {exc})")
    finally:
        await http.aclose()
