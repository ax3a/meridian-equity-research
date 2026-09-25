import type { DCFResult, DCFSensitivityPoint, ValuationResult } from "@/lib/types";
import { NULL_PLACEHOLDER, formatCurrency, formatPerShare, formatPercent } from "@/lib/format";
import { EmptyState } from "@/components/ui/States";

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "positive" | "negative";
}) {
  return (
    <div className="rounded-md border border-ink-700 bg-ink-900/40 p-3">
      <p className="text-xs text-ink-400">{label}</p>
      <p
        className={`text-lg font-semibold ${
          tone === "positive" ? "text-emerald-400" : tone === "negative" ? "text-red-400" : "text-ink-50"
        }`}
      >
        {value}
      </p>
      {sub && <p className="text-xs text-ink-500">{sub}</p>}
    </div>
  );
}

function SensitivityGrid({ sensitivity }: { sensitivity: DCFSensitivityPoint[] }) {
  const discountRates = [...new Set(sensitivity.map((s) => s.discount_rate))].sort((a, b) => a - b);
  const terminalGrowths = [...new Set(sensitivity.map((s) => s.terminal_growth))].sort((a, b) => a - b);
  const lookup = new Map(sensitivity.map((s) => [`${s.discount_rate}|${s.terminal_growth}`, s.value]));

  return (
    <div className="mt-4">
      <p className="mb-2 text-xs font-medium text-ink-300">
        Sensitivity — value per share (rows: terminal growth, columns: discount rate)
      </p>
      <div className="overflow-x-auto">
        <table className="text-xs">
          <thead>
            <tr>
              <th className="px-2 py-1" />
              {discountRates.map((d) => (
                <th key={d} className="px-2 py-1 text-right font-medium text-ink-400">
                  {formatPercent(d)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {terminalGrowths.map((g) => (
              <tr key={g}>
                <td className="px-2 py-1 font-medium text-ink-400">{formatPercent(g)}</td>
                {discountRates.map((d) => (
                  <td key={d} className="px-2 py-1 text-right tabular-nums text-ink-200">
                    {formatPerShare(lookup.get(`${d}|${g}`) ?? null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DcfSummary({ dcf }: { dcf: DCFResult }) {
  return (
    <div className="rounded-lg border border-ink-700 p-4">
      <h4 className="mb-3 text-sm font-semibold text-ink-100">Discounted Cash Flow</h4>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Value / Share" value={formatPerShare(dcf.value_per_share)} />
        <Stat label="Current Price" value={formatPerShare(dcf.current_price)} />
        <Stat
          label="Upside vs. Price"
          value={formatPercent(dcf.upside_pct)}
          tone={dcf.upside_pct == null ? undefined : dcf.upside_pct >= 0 ? "positive" : "negative"}
        />
        <Stat label="Equity Value" value={formatCurrency(dcf.equity_value)} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-ink-300 sm:grid-cols-3">
        <div className="flex justify-between gap-2 sm:block">
          <dt className="text-ink-500">Discount rate</dt>
          <dd>{formatPercent(dcf.assumptions.discount_rate)}</dd>
        </div>
        <div className="flex justify-between gap-2 sm:block">
          <dt className="text-ink-500">Terminal growth</dt>
          <dd>{formatPercent(dcf.assumptions.terminal_growth)}</dd>
        </div>
        <div className="flex justify-between gap-2 sm:block">
          <dt className="text-ink-500">FCF margin</dt>
          <dd>{formatPercent(dcf.assumptions.fcf_margin)}</dd>
        </div>
      </dl>
      {dcf.assumptions.rationale.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-400">
          {dcf.assumptions.rationale.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      )}
      {dcf.sensitivity.length > 0 && <SensitivityGrid sensitivity={dcf.sensitivity} />}
    </div>
  );
}

/** Valuation multiples table plus an optional DCF summary, from `ResearchReport.valuation`. */
export function ValuationPanel({ valuation }: { valuation: ValuationResult | null }) {
  if (!valuation) {
    return (
      <EmptyState
        title="No valuation available"
        description="The Valuation agent may have been skipped, or has not completed yet, for this run."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Price" value={formatPerShare(valuation.price)} sub={valuation.price_as_of ?? undefined} />
        <Stat label="Market Cap" value={formatCurrency(valuation.market_cap)} />
        <Stat label="Enterprise Value" value={formatCurrency(valuation.enterprise_value)} />
      </div>

      {valuation.multiples.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-ink-700">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="bg-ink-800/60 text-left text-xs uppercase tracking-wide text-ink-400">
              <tr>
                <th className="px-3 py-2 font-medium">Multiple</th>
                <th className="px-3 py-2 text-right font-medium">Value</th>
                <th className="px-3 py-2 text-right font-medium">Peer Median</th>
                <th className="px-3 py-2 text-right font-medium">Historical Median</th>
                <th className="px-3 py-2 font-medium">Basis</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-800">
              {valuation.multiples.map((multiple) => (
                <tr key={multiple.name}>
                  <td className="px-3 py-2 font-medium text-ink-100">{multiple.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink-200" title={multiple.note ?? undefined}>
                    {multiple.value === null ? NULL_PLACEHOLDER : `${multiple.value.toFixed(1)}x`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink-300">
                    {multiple.peer_median === null ? NULL_PLACEHOLDER : `${multiple.peer_median.toFixed(1)}x`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink-300">
                    {multiple.historical_median === null ? NULL_PLACEHOLDER : `${multiple.historical_median.toFixed(1)}x`}
                  </td>
                  <td className="px-3 py-2 text-xs text-ink-400">{multiple.basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No valuation multiples computed" />
      )}

      {valuation.dcf && <DcfSummary dcf={valuation.dcf} />}

      {valuation.methodology_notes.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-xs text-ink-400">
          {valuation.methodology_notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
