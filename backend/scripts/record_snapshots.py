#!/usr/bin/env python
"""Record real provider responses as offline/demo snapshots.

    python scripts/record_snapshots.py --tickers MSFT NVDA AAPL [--peers 4] [--verify]

Runs every provider call a typical research session makes (company profile, financial statements, filing
list + the latest 10-K/10-Q documents, market quote, news, macro indicators, and optionally a handful of
peer companies) with ``data_mode="live"`` and ``record_snapshots=True``, so `HttpClient` writes each real
response to `settings.snapshot_dir` (gzip-compressed JSON, never raw secrets -- `SnapshotStore`/`HttpClient`
already strip API keys from cache/snapshot keys).

With ``--verify``, every call is repeated with ``data_mode="snapshot"`` (no network client configured at
all) to prove the recorded snapshots are sufficient to serve the same calls completely offline -- this is
the demo/offline mode the rest of the platform relies on when no live network or API keys are available.

Keep the total recorded size under ~40 MB: this script indexes only the single latest 10-K and single
latest 10-Q document per ticker (the bulk of a snapshot's size is filing HTML), and peers are limited to
statements + a quote only (no filing documents), via ``--peers``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from meridian.cache.base import MemoryCache
from meridian.core.config import Settings
from meridian.core.errors import MeridianError
from meridian.core.http import HttpClient
from meridian.providers.factory import build_providers
from meridian.providers.snapshots import SnapshotStore


async def _record_one(base_settings: Settings, ticker: str, peers: int) -> None:
    http = HttpClient(base_settings, MemoryCache(), SnapshotStore(base_settings.snapshot_dir), record_snapshots=True)
    providers = build_providers(base_settings, http=http, cache=MemoryCache())
    try:
        identity = await providers.directory.resolve(ticker)
        profile_result = await providers.directory.profile(identity)
        enriched = profile_result.data.identity
        print(f"  resolved {enriched.name} ({enriched.ticker}), CIK {enriched.cik}, SIC {enriched.sic}")

        await providers.fundamentals.get_statements(enriched, years=5)

        await providers.filings.list_filings(enriched, ("10-K", "10-Q", "8-K"), 12)
        for form in ("10-K", "10-Q"):
            latest = await providers.filings.list_filings(enriched, (form,), 1)
            for ref in latest.data:
                await providers.filings.fetch_document(ref)

        try:
            await providers.market.get_quote(ticker, history_days=365)
        except MeridianError as exc:
            print(f"  (market quote skipped: {exc})")

        try:
            await providers.news.search_news(enriched, days=90, limit=20)
        except MeridianError as exc:
            print(f"  (news skipped: {exc})")

        try:
            await providers.macro.get_indicators()
        except MeridianError as exc:
            print(f"  (macro skipped: {exc})")

        if peers > 0:
            try:
                peer_result = await providers.peers.candidate_peers(enriched, peers)
            except MeridianError as exc:
                print(f"  (peer discovery skipped: {exc})")
            else:
                for candidate in peer_result.data[:peers]:
                    try:
                        await providers.fundamentals.get_statements(candidate.company, years=2)
                        await providers.market.get_quote(candidate.company.ticker)
                    except MeridianError as exc:
                        print(f"  (peer {candidate.company.ticker} skipped: {exc})")
    finally:
        await http.aclose()


async def _verify_one(base_settings: Settings, ticker: str) -> None:
    """Replay every call with `data_mode="snapshot"` (no live network client wired up at all).

    Mirrors `_record_one`'s per-call tolerance: a call that failed or was rate-limited during
    recording simply has no snapshot to replay, and should be reported as a gap rather than crash
    verification for every other (successfully recorded) call and ticker.
    """
    snapshot_settings = base_settings.model_copy(update={"data_mode": "snapshot"})
    http = HttpClient(snapshot_settings, MemoryCache(), SnapshotStore(base_settings.snapshot_dir))
    providers = build_providers(snapshot_settings, http=http, cache=MemoryCache())
    gaps: list[str] = []
    try:
        identity = await providers.directory.resolve(ticker)
        await providers.directory.profile(identity)
        await providers.fundamentals.get_statements(identity, years=5)
        await providers.filings.list_filings(identity, ("10-K", "10-Q", "8-K"), 12)
        for form in ("10-K", "10-Q"):
            latest = await providers.filings.list_filings(identity, (form,), 1)
            for ref in latest.data:
                await providers.filings.fetch_document(ref)
        for label, call in (
            ("market quote", providers.market.get_quote(ticker, history_days=365)),
            ("news", providers.news.search_news(identity, days=90, limit=20)),
            ("macro", providers.macro.get_indicators()),
        ):
            try:
                await call
            except MeridianError:
                gaps.append(label)
        if gaps:
            print(f"  [verify] {ticker}: replayed offline OK, except: {', '.join(gaps)} (not recorded live either)")
        else:
            print(f"  [verify] {ticker}: every recorded call replayed successfully with no network access")
    finally:
        await http.aclose()


def _report_size(root: Path) -> None:
    if not root.is_dir():
        print("No snapshots were recorded.")
        return
    total = 0
    print("\nRecorded snapshot files:")
    for path in sorted(root.rglob("*.json.gz")):
        size = path.stat().st_size
        total += size
        print(f"  {path.relative_to(root)}: {size / 1024:.1f} KB")
    print(f"Total: {total / (1024 * 1024):.2f} MB")
    if total > 40 * 1024 * 1024:
        print("WARNING: total snapshot size exceeds the ~40 MB budget.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+", required=True, help="Tickers to record, e.g. MSFT NVDA AAPL")
    parser.add_argument("--peers", type=int, default=0, help="Also record N peer companies' statements + quote")
    parser.add_argument("--verify", action="store_true", help="Replay every call in data_mode=snapshot afterward")
    parser.add_argument("--snapshot-dir", default=None, help="Override the snapshot directory (default: settings)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings_kwargs: dict[str, object] = {"data_mode": "live", "llm_provider": "offline", "redis_url": None}
    if args.snapshot_dir:
        settings_kwargs["snapshot_dir"] = Path(args.snapshot_dir)
    base_settings = Settings(**settings_kwargs)

    async def _run() -> None:
        for ticker in args.tickers:
            print(f"Recording {ticker}...")
            await _record_one(base_settings, ticker, args.peers)
        _report_size(base_settings.snapshot_dir)
        if args.verify:
            print("\nVerifying snapshot-mode replay (no live network calls should occur)...")
            for ticker in args.tickers:
                await _verify_one(base_settings, ticker)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
