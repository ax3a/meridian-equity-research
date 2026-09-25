import type { CriticReview, Severity } from "@/lib/types";
import { humanizeEnum } from "@/lib/format";
import { StatusChip } from "@/components/ui/StatusChip";

const SEVERITY_CLASSES: Record<Severity, string> = {
  low: "text-ink-300",
  medium: "text-amber-400",
  high: "text-red-400",
};

/** The critic's verdict for one revision round, with per-section verdicts and issue lists. */
export function CriticPanel({ review }: { review: CriticReview }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-semibold text-ink-100">Round {review.round}</h4>
        <StatusChip status={review.overall_verdict} kind="verdict" />
      </div>
      <p className="text-sm text-ink-300">{review.summary}</p>
      <div className="space-y-2">
        {review.reviews.map((sectionReview) => (
          <div key={sectionReview.agent} className="rounded-md border border-ink-700 p-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-ink-100">{humanizeEnum(sectionReview.agent)}</span>
              <StatusChip status={sectionReview.verdict} kind="verdict" />
            </div>
            {sectionReview.issues.length > 0 && (
              <ul className="space-y-1 text-xs">
                {sectionReview.issues.map((issue, i) => (
                  <li key={i} className={SEVERITY_CLASSES[issue.severity]}>
                    <span className="font-medium">{humanizeEnum(issue.issue_type)}:</span> {issue.description}
                    {issue.suggested_fix && <span className="block text-ink-400">Fix: {issue.suggested_fix}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      {review.checks_run.length > 0 && (
        <p className="text-xs text-ink-500">Checks run: {review.checks_run.join(", ")}</p>
      )}
    </div>
  );
}
