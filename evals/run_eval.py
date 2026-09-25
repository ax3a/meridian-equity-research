"""Run the benchmark suite and write a JSON result plus a Markdown scorecard.

    python evals/run_eval.py --cases msft,nvda_focus
    python evals/run_eval.py --snapshot          # offline, recorded data only
    python evals/run_eval.py --all

Runs are real: the same graph, agents, tools and providers the API uses. Expect 2-3 minutes per case
against live SEC data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPO_ROOT))

from meridian.agents.base import AgentDeps
from meridian.agents.critic import Critic
from meridian.agents.registry import build_agent_set
from meridian.core.config import Settings
from meridian.core.errors import MeridianError
from meridian.graph.runner import ResearchRunner
from meridian.memory.inmemory import InMemoryResearchMemoryStore
from meridian.observability.events import ListEventSink
from meridian.providers.factory import build_providers, build_retriever
from meridian.rag.pipeline import build_retriever as build_rag_retriever
from meridian.schemas.enums import RunStatus
from meridian.schemas.research import ResearchRequest
from meridian.tools.factory import build_tool_registry

from evals import metrics as m
from evals.cases import BY_KEY, CASES, EvalCase
from evals.injection import (
    HOSTILE_FILING_HTML,
    _StubFilingsProvider,
    run_injection_eval,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _settings(snapshot: bool) -> Settings:
    return Settings(
        redis_url=None,
        data_mode="snapshot" if snapshot else "auto",
        llm_provider="offline",
        embedding_provider="hashing",
        require_approval_default=False,
        sec_user_agent="Meridian Eval Suite eval@example.com",
    )


def _build_deps(settings: Settings) -> AgentDeps:
    events = ListEventSink()
    providers = build_providers(settings)
    return AgentDeps(
        settings=settings,
        providers=providers,
        tools=build_tool_registry(),
        retriever=build_retriever(settings, providers),
        events=events,
        memory=InMemoryResearchMemoryStore(),
    )


async def run_case(case: EvalCase, settings: Settings) -> dict[str, Any]:
    deps = _build_deps(settings)
    runner = ResearchRunner(build_agent_set(deps), settings)
    started = time.perf_counter()
    record: dict[str, Any] = {"case": case.key, "query": case.query, "why": case.why}

    try:
        session_id = await runner.start(
            ResearchRequest(query=case.query, ticker=case.ticker, depth=case.depth, require_approval=False)
        )
        await runner.wait_idle(session_id)
        state = await runner.status(session_id)
    except MeridianError as exc:
        elapsed = time.perf_counter() - started
        record.update(
            {
                "status": "failed",
                "error": exc.message,
                "latency_seconds": round(elapsed, 1),
                "passed": case.expect_failure,
                "notes": "failed as expected" if case.expect_failure else "unexpected failure",
            }
        )
        return record

    elapsed = time.perf_counter() - started
    if state is None:
        record.update({"status": "missing", "passed": False, "notes": "runner returned no state"})
        return record

    failed_cleanly = state.status == RunStatus.FAILED
    if case.expect_failure:
        record.update(
            {
                "status": state.status.value,
                "passed": failed_cleanly,
                "latency_seconds": round(elapsed, 1),
                "error": state.errors[0].message if state.errors else None,
                "notes": "failed cleanly" if failed_cleanly else "expected a clean failure, got a run",
            }
        )
        return record

    scored = m.score_run(
        state,
        expected=case.expected_agents,
        forbidden=case.forbidden_agents,
        latency_s=elapsed,
        required_sections=case.required_sections,
    )
    resolved = state.company.ticker if state.company else None
    absent_ok, absent_detail = _check_absent_metrics(state, case)

    record.update(
        {
            "status": state.status.value,
            "resolved_ticker": resolved,
            "expected_ticker": case.expected_ticker,
            "ticker_correct": case.expected_ticker is None or resolved == case.expected_ticker,
            "metrics": [metric.as_dict() for metric in scored],
            "absent_metrics_ok": absent_ok,
            "absent_metrics_detail": absent_detail,
            "latency_seconds": round(elapsed, 1),
        }
    )
    record["passed"] = bool(
        record["ticker_correct"]
        and absent_ok
        and state.report is not None
        and _metric_value(scored, "source_correctness") in (None, 1.0)
    )
    return record


def _metric_value(scored: list[m.Metric], name: str) -> float | None:
    for metric in scored:
        if metric.name == name:
            return metric.value
    return None


def _check_absent_metrics(state: Any, case: EvalCase) -> tuple[bool, str]:
    """For a bank, certain metrics must be absent or explicitly not-meaningful rather than a number."""
    if not case.expect_absent_metrics or state.metrics is None:
        return True, "not applicable"
    offenders = [
        f"{ref}={metric.value}"
        for ref, metric in state.metrics.values.items()
        if metric.key in case.expect_absent_metrics and metric.value is not None
    ]
    return not offenders, "; ".join(offenders) if offenders else "all correctly absent"


async def run_injection_case(settings: Settings) -> dict[str, Any]:
    retriever = build_rag_retriever(settings, _StubFilingsProvider(HOSTILE_FILING_HTML))
    deps = _build_deps(settings)
    report = await run_injection_eval(retriever, critic=Critic(deps))
    return {"case": "prompt_injection", "passed": report.passed, **report.as_dict()}


def render_markdown(results: list[dict[str, Any]], settings: Settings) -> str:
    lines = [
        "# Meridian evaluation scorecard",
        "",
        (f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} · "
        f"LLM mode: **{settings.llm_mode}** · data mode: **{settings.data_mode}**"),
        "",
        "Offline LLM mode means narrative text is template-based; figures and citations are real either way.",
        "",
        "## Cases",
        "",
        "| Case | Resolved | Passed | Latency | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if r["case"] == "prompt_injection":
            continue
        lines.append(
            f"| `{r['case']}` | {r.get('resolved_ticker') or '-'} | {'yes' if r.get('passed') else 'NO'} "
            f"| {r.get('latency_seconds', '-')}s | {r.get('notes') or r.get('error') or ''} |"
        )

    lines += ["", "## Metrics by case", ""]
    for r in results:
        if not r.get("metrics"):
            continue
        lines += [f"### {r['case']}", "", "| Metric | Value | Detail |", "| --- | --- | --- |"]
        for metric in r["metrics"]:
            value = metric["value"]
            shown = "n/a" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))
            lines.append(f"| {metric['name']} | {shown} | {metric['detail']} |")
        lines.append("")

    injection = next((r for r in results if r["case"] == "prompt_injection"), None)
    if injection:
        lines += [
            "## Prompt injection",
            "",
            f"Result: **{'passed' if injection['passed'] else 'FAILED'}**",
            "",
            (f"- chunks flagged: {injection['flagged_chunks']}/{injection['total_chunks']} "
            f"(patterns: {', '.join(injection['flags_seen']) or 'none'})"),
            f"- hostile text confined to an untrusted-evidence block: {injection['evidence_contained']}",
            f"- forged block delimiters neutralised: {injection['delimiters_neutralised']}",
            f"- instruction leaked into the system prompt: {injection['instruction_outside_evidence']}",
            (f"- planted figure rejected by the critic: {injection['planted_figure_rejected']} "
            f"(issues: {', '.join(injection['critic_issue_types']) or 'none'})"),
            "",
        ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Meridian evaluation suite.")
    parser.add_argument("--cases", help="comma-separated case keys (default: all)")
    parser.add_argument("--snapshot", action="store_true", help="use recorded data only (no network)")
    parser.add_argument("--skip-injection", action="store_true")
    parser.add_argument("--json", dest="json_path", help="also write the raw JSON here")
    args = parser.parse_args()

    settings = _settings(args.snapshot)
    selected = [BY_KEY[k.strip()] for k in args.cases.split(",")] if args.cases else list(CASES)

    results: list[dict[str, Any]] = []
    for case in selected:
        print(f"[eval] {case.key}: {case.query}", flush=True)
        result = await run_case(case, settings)
        print(f"       -> {result.get('status')} passed={result.get('passed')}", flush=True)
        results.append(result)

    if not args.skip_injection:
        print("[eval] prompt_injection", flush=True)
        injection_result = await run_injection_case(settings)
        print(f"       -> passed={injection_result['passed']}", flush=True)
        results.append(injection_result)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "llm_mode": settings.llm_mode,
        "data_mode": settings.data_mode,
        "results": results,
    }
    (RESULTS_DIR / f"{stamp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    scorecard = render_markdown(results, settings)
    (RESULTS_DIR / "latest.md").write_text(scorecard, encoding="utf-8")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n" + scorecard)
    failed = [r["case"] for r in results if not r.get("passed")]
    print(f"\n{len(results) - len(failed)}/{len(results)} cases passed" + (f"; failed: {failed}" if failed else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
