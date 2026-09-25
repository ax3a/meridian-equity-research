"use client";

import { useState } from "react";
import type { AgentRunView, ToolCallRecord, UsageBreakdown } from "@/lib/types";
import { StatusChip } from "@/components/ui/StatusChip";
import { formatCurrency, formatDuration, humanizeEnum } from "@/lib/format";

function summarizeArguments(args: Record<string, unknown>): string {
  try {
    const text = JSON.stringify(args);
    return text.length > 0 ? text : "{}";
  } catch {
    return "(unserializable arguments)";
  }
}

interface AgentRunRowProps {
  run: AgentRunView;
  toolCalls: ToolCallRecord[];
}

function AgentRunRow({ run, toolCalls }: AgentRunRowProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border border-ink-700">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center justify-between gap-3 p-3 text-left"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink-100">{humanizeEnum(run.agent)}</span>
            <StatusChip status={run.status} kind="task" />
            {run.revision > 0 && (
              <span className="text-xs font-medium uppercase tracking-wide text-amber-400">rev {run.revision}</span>
            )}
          </div>
          <p className="mt-1 max-w-xl truncate text-xs text-ink-400">{run.objective}</p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-3 text-xs text-ink-400">
          <span>Wave {run.wave}</span>
          <span>{formatDuration(run.duration_ms)}</span>
          <span aria-hidden="true">{open ? "−" : "+"}</span>
        </div>
      </button>
      {open && (
        <div className="space-y-3 border-t border-ink-800 p-3">
          {run.error && <p className="text-sm text-red-400">{run.error}</p>}
          {run.summary && <p className="text-sm text-ink-300">{run.summary}</p>}
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">
              Tool calls ({toolCalls.length})
            </p>
            {toolCalls.length === 0 ? (
              <p className="text-xs text-ink-500">No tool calls recorded.</p>
            ) : (
              <div className="overflow-x-auto rounded-md border border-ink-800">
                <table className="w-full text-xs">
                  <thead className="bg-ink-900 text-left uppercase tracking-wide text-ink-500">
                    <tr>
                      <th className="px-2 py-1 font-medium">Tool</th>
                      <th className="px-2 py-1 font-medium">Status</th>
                      <th className="px-2 py-1 text-right font-medium">Duration</th>
                      <th className="px-2 py-1 font-medium">Arguments</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-800">
                    {toolCalls.map((tc) => (
                      <tr key={tc.id}>
                        <td className="px-2 py-1 font-mono text-ink-200">{tc.tool}</td>
                        <td className="px-2 py-1">
                          <StatusChip status={tc.status} kind="task" label={humanizeEnum(tc.status)} pulse={false} />
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums text-ink-300">
                          {formatDuration(tc.duration_ms)}
                        </td>
                        <td
                          className="max-w-xs truncate px-2 py-1 font-mono text-ink-400"
                          title={summarizeArguments(tc.arguments)}
                        >
                          {summarizeArguments(tc.arguments)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {run.findings.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">
                Findings ({run.findings.length})
              </p>
              <ul className="list-disc space-y-1 pl-5 text-xs text-ink-300">
                {run.findings.map((f) => (
                  <li key={f.id}>{f.claim}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Per-agent rows with nested tool calls. Renders only task/tool status summaries, never model reasoning. */
export function TraceAgentRuns({ runs, toolCalls }: { runs: AgentRunView[]; toolCalls: ToolCallRecord[] }) {
  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <AgentRunRow key={run.task_id} run={run} toolCalls={toolCalls.filter((tc) => tc.agent === run.agent)} />
      ))}
    </div>
  );
}

interface UsageTableProps {
  usage: UsageBreakdown[];
  totalTokens: number;
  totalCostUsd: number;
}

export function UsageTable({ usage, totalTokens, totalCostUsd }: UsageTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-ink-700">
      <table className="w-full text-sm">
        <thead className="bg-ink-800/60 text-left text-xs uppercase tracking-wide text-ink-400">
          <tr>
            <th className="px-3 py-2 font-medium">Agent</th>
            <th className="px-3 py-2 font-medium">Model</th>
            <th className="px-3 py-2 text-right font-medium">Calls</th>
            <th className="px-3 py-2 text-right font-medium">Input Tokens</th>
            <th className="px-3 py-2 text-right font-medium">Output Tokens</th>
            <th className="px-3 py-2 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-800">
          {usage.map((u, i) => (
            <tr key={`${u.agent}-${u.model}-${i}`}>
              <td className="px-3 py-2 text-ink-100">{humanizeEnum(u.agent)}</td>
              <td className="px-3 py-2 font-mono text-xs text-ink-300">{u.model}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{u.calls}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{u.input_tokens.toLocaleString()}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">{u.output_tokens.toLocaleString()}</td>
              <td className="px-3 py-2 text-right tabular-nums text-ink-200">
                {formatCurrency(u.cost_usd, { decimals: 4, compact: false })}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-ink-700 font-medium text-ink-100">
            <td className="px-3 py-2" colSpan={3}>
              Total
            </td>
            <td className="px-3 py-2 text-right tabular-nums" colSpan={2}>
              {totalTokens.toLocaleString()} tokens
            </td>
            <td className="px-3 py-2 text-right tabular-nums">
              {formatCurrency(totalCostUsd, { decimals: 4, compact: false })}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
