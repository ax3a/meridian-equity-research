import type { MetricRow } from "@/lib/types";
import { formatByUnit } from "@/lib/format";
import { EmptyState } from "@/components/ui/States";

const PERIOD_PRIORITY = ["TTM", "current"];

function sortPeriods(periods: string[]): string[] {
  const fiscalYears = periods.filter((p) => /^FY\d{4}$/.test(p)).sort();
  const others = periods.filter((p) => !/^FY\d{4}$/.test(p));
  others.sort((a, b) => {
    const ai = PERIOD_PRIORITY.indexOf(a);
    const bi = PERIOD_PRIORITY.indexOf(b);
    if (ai !== -1 || bi !== -1) return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    return a.localeCompare(b);
  });
  return [...fiscalYears, ...others];
}

/** The report's key-metrics table: one row per `MetricRow`, one column per period present across all rows. */
export function MetricsTable({ rows }: { rows: MetricRow[] }) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No key metrics yet"
        description="Metrics appear once the Financials agent has computed them from the underlying filings."
      />
    );
  }

  const periodSet = new Set<string>();
  for (const row of rows) {
    for (const period of Object.keys(row.values)) periodSet.add(period);
  }
  const periods = sortPeriods([...periodSet]);

  return (
    <div className="overflow-x-auto rounded-lg border border-ink-700">
      <table className="w-full min-w-[480px] text-sm">
        <thead className="bg-ink-800/60 text-left text-xs uppercase tracking-wide text-ink-400">
          <tr>
            <th className="px-3 py-2 font-medium">Metric</th>
            {periods.map((period) => (
              <th key={period} className="px-3 py-2 text-right font-medium">
                {period}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {rows.map((row) => (
            <tr key={row.key} className="hover:bg-ink-800/30">
              <td className="px-3 py-2 font-medium text-ink-100" title={row.formula}>
                {row.label}
              </td>
              {periods.map((period) => (
                <td key={period} className="px-3 py-2 text-right tabular-nums text-ink-200">
                  {formatByUnit(row.values[period], row.unit)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
