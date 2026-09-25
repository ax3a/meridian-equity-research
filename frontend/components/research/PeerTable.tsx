import type { PeerComparison } from "@/lib/types";
import { formatCurrency, formatMultiple, formatPercent } from "@/lib/format";
import { EmptyState } from "@/components/ui/States";

/** Peer comparison table: one row per company (including the target, highlighted). */
export function PeerTable({ peers }: { peers: PeerComparison | null }) {
  if (!peers || peers.peers.length === 0) {
    return (
      <EmptyState
        title="No peer comparison available"
        description="The Competitors agent may have been skipped, or has not completed yet, for this run."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-ink-700">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="bg-ink-800/60 text-left text-xs uppercase tracking-wide text-ink-400">
          <tr>
            <th className="px-3 py-2 font-medium">Company</th>
            <th className="px-3 py-2 text-right font-medium">Revenue</th>
            <th className="px-3 py-2 text-right font-medium">Rev Growth</th>
            <th className="px-3 py-2 text-right font-medium">Gross Margin</th>
            <th className="px-3 py-2 text-right font-medium">Op Margin</th>
            <th className="px-3 py-2 text-right font-medium">Net Margin</th>
            <th className="px-3 py-2 text-right font-medium">Market Cap</th>
            <th className="px-3 py-2 text-right font-medium">P/E</th>
            <th className="px-3 py-2 text-right font-medium">EV/Sales</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {peers.peers.map((peer) => (
            <tr
              key={peer.company.ticker}
              className={peer.is_target ? "bg-accent-600/10 font-medium" : "hover:bg-ink-800/30"}
            >
              <td className="px-3 py-2">
                <div className="text-ink-100">{peer.company.name}</div>
                <div className="text-xs text-ink-400">
                  {peer.company.ticker}
                  {peer.is_target ? " · target" : ""}
                </div>
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatCurrency(peer.revenue)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatPercent(peer.revenue_growth)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatPercent(peer.gross_margin)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatPercent(peer.operating_margin)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatPercent(peer.net_margin)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatCurrency(peer.market_cap)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatMultiple(peer.pe)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{formatMultiple(peer.ev_sales)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-ink-800 px-3 py-2 text-xs text-ink-400">
        Selection method: {peers.selection_method}
      </p>
    </div>
  );
}
