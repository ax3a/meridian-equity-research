import { humanizeEnum } from "@/lib/format";

type Tone = "neutral" | "info" | "progress" | "success" | "warning" | "danger";

const TASK_STATUS_TONE: Record<string, Tone> = {
  pending: "neutral",
  running: "progress",
  completed: "success",
  failed: "danger",
  skipped: "neutral",
};

const RUN_STATUS_TONE: Record<string, Tone> = {
  queued: "neutral",
  planning: "info",
  researching: "progress",
  reviewing: "info",
  revising: "warning",
  awaiting_approval: "warning",
  writing: "progress",
  completed: "success",
  failed: "danger",
  cancelled: "neutral",
};

const VERDICT_TONE: Record<string, Tone> = {
  approved: "success",
  needs_revision: "warning",
  rejected: "danger",
};

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "border-ink-600 bg-ink-700/60 text-ink-200",
  info: "border-accent-600/40 bg-accent-600/15 text-accent-400",
  progress: "border-amber-500/40 bg-amber-500/15 text-amber-400",
  success: "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
  warning: "border-amber-500/40 bg-amber-500/15 text-amber-400",
  danger: "border-red-500/40 bg-red-500/15 text-red-400",
};

export type StatusKind = "task" | "run" | "verdict";

export function toneForStatus(status: string, kind: StatusKind): Tone {
  const map = kind === "run" ? RUN_STATUS_TONE : kind === "verdict" ? VERDICT_TONE : TASK_STATUS_TONE;
  return map[status] ?? "neutral";
}

interface StatusChipProps {
  status: string;
  kind?: StatusKind;
  label?: string;
  pulse?: boolean;
}

export function StatusChip({ status, kind = "task", label, pulse }: StatusChipProps) {
  const tone = toneForStatus(status, kind);
  const shouldPulse = pulse ?? (kind === "task" ? status === "running" : status === "researching" || status === "writing");
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {shouldPulse && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden="true" />}
      {label ?? humanizeEnum(status)}
    </span>
  );
}
