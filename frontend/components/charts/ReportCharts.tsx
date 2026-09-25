import type { ChartSeries, PeerComparison } from "@/lib/types";
import { TimeSeriesChart } from "./TimeSeriesChart";
import { PeerMultipleChart } from "./PeerMultipleChart";

/**
 * Looks up canonical financial-engine metric keys (see `FINANCIAL_METRIC_KEYS` in `lib/types.ts`, sourced
 * from the implementation plan's Task 1 metric key list) inside `report.charts`. `ChartSeries.key` is not
 * otherwise constrained by the schema, so this is a best-effort, gracefully-degrading lookup: any chart
 * whose keys aren't present renders its own empty state instead of failing the page.
 */
function pickSeries(charts: ChartSeries[], keys: string[]): ChartSeries[] {
  const byKey = new Map(charts.map((c) => [c.key, c]));
  return keys.map((k) => byKey.get(k)).filter((s): s is ChartSeries => s !== undefined);
}

interface ReportChartsProps {
  charts: ChartSeries[];
  peers: PeerComparison | null;
}

export function ReportCharts({ charts, peers }: ReportChartsProps) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <TimeSeriesChart title="Revenue" series={pickSeries(charts, ["revenue"])} kind="bar" />
      <TimeSeriesChart title="Net Income" series={pickSeries(charts, ["net_income"])} kind="bar" />
      <TimeSeriesChart title="Free Cash Flow" series={pickSeries(charts, ["free_cash_flow"])} kind="bar" />
      <TimeSeriesChart
        title="Margins"
        series={pickSeries(charts, ["gross_margin", "operating_margin", "net_margin"])}
        kind="line"
      />
      <TimeSeriesChart title="Diluted EPS" series={pickSeries(charts, ["eps_diluted"])} kind="line" />
      <TimeSeriesChart title="Revenue Growth (YoY)" series={pickSeries(charts, ["revenue_growth"])} kind="bar" />
      <TimeSeriesChart
        title="Cash & Investments vs. Total Debt"
        series={pickSeries(charts, ["cash_and_investments", "total_debt"])}
        kind="bar"
      />
      <PeerMultipleChart peers={peers} />
    </div>
  );
}
