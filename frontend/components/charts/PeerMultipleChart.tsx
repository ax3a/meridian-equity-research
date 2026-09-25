"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PeerComparison } from "@/lib/types";
import { formatMultiple } from "@/lib/format";
import { EmptyState } from "@/components/ui/States";

const GRID_STROKE = "#212a3d";
const AXIS_STROKE = "#6b7a99";
const TOOLTIP_STYLE = { background: "#161d2b", border: "1px solid #2e3a52", borderRadius: 8, fontSize: 12 };

interface PeerBar {
  ticker: string;
  isTarget: boolean;
  pe: number | null;
  ev_sales: number | null;
}

/**
 * Valuation-multiple peer comparison chart. `PeerSnapshot` only carries `pe` and `ev_sales` (not
 * ev_ebitda/price_fcf/price_sales, even though `ValuationMultiple` supports those) — see the frontend
 * task report for this as a noted contract gap. Built from `report.peers`, not `report.charts`, since
 * `ChartSeries` is period-indexed and has no notion of "one bar per company".
 */
export function PeerMultipleChart({ peers }: { peers: PeerComparison | null }) {
  if (!peers || peers.peers.length === 0) {
    return (
      <div className="rounded-lg border border-ink-700 p-4">
        <h4 className="mb-2 text-sm font-semibold text-ink-100">Valuation Multiples vs. Peers</h4>
        <EmptyState title="No peer data" description="The Competitors agent may have been skipped for this run." />
      </div>
    );
  }

  const data: PeerBar[] = peers.peers.map((p) => ({
    ticker: p.company.ticker,
    isTarget: p.is_target,
    pe: p.pe,
    ev_sales: p.ev_sales,
  }));

  return (
    <div className="rounded-lg border border-ink-700 p-4">
      <h4 className="mb-2 text-sm font-semibold text-ink-100">Valuation Multiples vs. Peers</h4>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
            <XAxis dataKey="ticker" stroke={AXIS_STROKE} fontSize={12} />
            <YAxis stroke={AXIS_STROKE} fontSize={12} width={48} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value: number) => formatMultiple(value)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="pe" name="P/E" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            <Bar dataKey="ev_sales" name="EV/Sales" fill="#f59e0b" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-ink-500">
        Limited to P/E and EV/Sales — the only multiples carried on each peer snapshot.
      </p>
    </div>
  );
}
