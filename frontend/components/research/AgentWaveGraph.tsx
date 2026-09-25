import type { AgentProgress, AgentRunView } from "@/lib/types";
import { StatusChip } from "@/components/ui/StatusChip";
import { EmptyState } from "@/components/ui/States";
import { formatDuration, humanizeEnum } from "@/lib/format";

interface AgentNodeCardProps {
  agent: AgentProgress;
  run?: AgentRunView;
}

function AgentNodeCard({ agent, run }: AgentNodeCardProps) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900/50 p-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="font-medium text-ink-100">{humanizeEnum(agent.agent)}</span>
        <StatusChip status={agent.status} kind="task" />
      </div>
      {agent.objective && <p className="mb-2 text-xs text-ink-300">{agent.objective}</p>}
      {agent.revision > 0 && (
        <span className="mb-2 inline-block rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-400">
          Revision {agent.revision}
        </span>
      )}
      <div className="mt-2 border-t border-ink-800 pt-2 text-xs text-ink-400">
        {run ? (
          <>
            {run.tools_used.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {run.tools_used.map((tool) => (
                  <span key={tool} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-300">
                    {tool}
                  </span>
                ))}
              </div>
            ) : (
              <span>No tool calls recorded</span>
            )}
            {run.duration_ms != null && <p className="mt-1">Duration: {formatDuration(run.duration_ms)}</p>}
            {run.error && <p className="mt-1 text-red-400">{run.error}</p>}
          </>
        ) : (
          <span>{agent.status === "pending" ? "Not started yet" : "Working..."}</span>
        )}
      </div>
    </div>
  );
}

interface AgentWaveGraphProps {
  agents: AgentProgress[];
  runsByAgent: Map<string, AgentRunView>;
}

/**
 * The wave-by-wave agent graph: the central visual for making the multi-agent run legible. Groups
 * `StatusView.agents` by wave, rendering each agent's live status; once an agent's task completes its
 * `AgentRunView` (tool names used, duration, error) is layered in from `GET /research/{id}/agents`.
 */
export function AgentWaveGraph({ agents, runsByAgent }: AgentWaveGraphProps) {
  if (agents.length === 0) {
    return (
      <EmptyState
        title="Plan not yet created"
        description="The agent graph appears once the supervisor produces a plan and dispatches the first wave."
      />
    );
  }

  const waves = [...new Set(agents.map((a) => a.wave))].sort((a, b) => a - b);

  return (
    <div className="space-y-6">
      {waves.map((wave) => (
        <div key={wave}>
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink-800 text-xs font-semibold text-ink-200">
              {wave}
            </span>
            <h4 className="text-sm font-semibold text-ink-100">Wave {wave}</h4>
            <div className="h-px flex-1 bg-ink-800" />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {agents
              .filter((a) => a.wave === wave)
              .map((a) => (
                <AgentNodeCard key={`${a.agent}-${wave}-${a.revision}`} agent={a} run={runsByAgent.get(a.agent)} />
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}
