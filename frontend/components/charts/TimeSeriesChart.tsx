"use client";

import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ChartSeries } from "@/lib/types";
import { formatByUnit } from "@/lib/format";
import { EmptyState } from "@/components/ui/States";

const DEFAULT_COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#a78bfa"];
const GRID_STROKE = "#212a3d";
const AXIS_STROKE = "#6b7a99";
const TOOLTIP_STYLE = { background: "#161d2b", border: "1px solid #2e3a52", borderRadius: 8, fontSize: 12 };

interface ChartRow {
  period: string;
  [seriesKey: string]: string | number | null;
}

function buildRows(series: ChartSeries[]): ChartRow[] {
  const periodOrder: string[] = [];
  const rows = new Map<string, ChartRow>();
  for (const s of series) {
    for (const point of s.points) {
      let row = rows.get(point.period);
      if (!row) {
        row = { period: point.period };
        rows.set(point.period, row);
        periodOrder.push(point.period);
      }
      row[s.key] = point.value;
    }
  }
  return periodOrder.map((period) => rows.get(period)!);
}

function labelFor(series: ChartSeries[], key: string): string {
  return series.find((s) => s.key === key)?.label ?? key;
}

interface TimeSeriesChartProps {
  title: string;
  series: ChartSeries[];
  kind?: "bar" | "line";
  colors?: string[];
  footnote?: string;
}

/**
 * Renders one or more `ChartSeries` sharing a period axis (e.g. gross/operating/net margin together as
 * "Margins"). Series whose points are all null are dropped; if nothing usable remains, shows an empty
 * state rather than an empty chart — this is expected for a run where an agent was skipped or a metric
 * could not be computed from the available filings.
 */
export function TimeSeriesChart({ title, series, kind = "bar", colors = DEFAULT_COLORS, footnote }: TimeSeriesChartProps) {
  const usable = series.filter((s) => s.points.some((p) => p.value !== null));

  if (usable.length === 0) {
    return (
      <div className="rounded-lg border border-ink-700 p-4">
        <h4 className="mb-2 text-sm font-semibold text-ink-100">{title}</h4>
        <EmptyState title="No data" description="This chart's underlying metric was not available for this run." />
      </div>
    );
  }

  const data = buildRows(usable);
  const unit = usable[0]!.unit;
  const tickFormatter = (value: number) => formatByUnit(value, unit);
  const tooltipFormatter = (value: number, name: string): [string, string] => [
    formatByUnit(value, unit),
    labelFor(usable, name),
  ];
  const legendFormatter = (name: string) => labelFor(usable, name);

  return (
    <div className="rounded-lg border border-ink-700 p-4">
      <h4 className="mb-2 text-sm font-semibold text-ink-100">{title}</h4>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {kind === "line" ? (
            <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
              <XAxis dataKey="period" stroke={AXIS_STROKE} fontSize={12} />
              <YAxis stroke={AXIS_STROKE} fontSize={12} width={64} tickFormatter={tickFormatter} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={tooltipFormatter} />
              {usable.length > 1 && <Legend formatter={legendFormatter} wrapperStyle={{ fontSize: 12 }} />}
              {usable.map((s, i) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.key}
                  stroke={colors[i % colors.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
              <XAxis dataKey="period" stroke={AXIS_STROKE} fontSize={12} />
              <YAxis stroke={AXIS_STROKE} fontSize={12} width={64} tickFormatter={tickFormatter} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={tooltipFormatter} />
              {usable.length > 1 && <Legend formatter={legendFormatter} wrapperStyle={{ fontSize: 12 }} />}
              {usable.map((s, i) => (
                <Bar key={s.key} dataKey={s.key} name={s.key} fill={colors[i % colors.length]} radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {footnote && <p className="mt-2 text-xs text-ink-500">{footnote}</p>}
    </div>
  );
}
