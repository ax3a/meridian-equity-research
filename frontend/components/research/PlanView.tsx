import type { ResearchPlan } from "@/lib/types";
import { humanizeEnum } from "@/lib/format";
import { StatusChip } from "@/components/ui/StatusChip";

/** The supervisor's plan: objectives, rationale, tasks grouped by wave, and any skipped agents. */
export function PlanView({ plan }: { plan: ResearchPlan }) {
  const waves = [...new Set(plan.tasks.map((t) => t.wave))].sort((a, b) => a - b);
  const skipped = Object.entries(plan.skipped_agents);

  return (
    <div className="space-y-4">
      {plan.objectives.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">Objectives</h4>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-200">
            {plan.objectives.map((objective, i) => (
              <li key={i}>{objective}</li>
            ))}
          </ul>
        </div>
      )}

      {plan.rationale && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">Rationale</h4>
          <p className="text-sm text-ink-300">{plan.rationale}</p>
        </div>
      )}

      <div className="space-y-3">
        {waves.map((wave) => (
          <div key={wave}>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">Wave {wave}</h4>
            <ul className="space-y-1">
              {plan.tasks
                .filter((t) => t.wave === wave)
                .map((task) => (
                  <li
                    key={task.id}
                    className="flex items-start justify-between gap-3 rounded-md border border-ink-700 bg-ink-900/40 p-2 text-sm"
                  >
                    <div className="min-w-0">
                      <span className="font-medium text-ink-100">{humanizeEnum(task.agent)}</span>
                      <p className="text-ink-300">{task.objective}</p>
                    </div>
                    <StatusChip status={task.status} kind="task" />
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>

      {skipped.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">Skipped agents</h4>
          <ul className="space-y-1 text-sm text-ink-400">
            {skipped.map(([agent, reason]) => (
              <li key={agent}>
                <span className="font-medium text-ink-200">{humanizeEnum(agent)}:</span> {reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
