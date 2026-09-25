"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, getReport, getResearch } from "@/lib/api";
import type { Citation, ResearchDetail, ResearchReport } from "@/lib/types";
import { buildCitationOrder } from "@/lib/citations";
import { formatDateTime } from "@/lib/format";
import { RunHeader } from "@/components/research/RunHeader";
import { CitationText } from "@/components/research/CitationText";
import { CitationDrawer } from "@/components/research/CitationDrawer";
import { MetricsTable } from "@/components/research/MetricsTable";
import { PeerTable } from "@/components/research/PeerTable";
import { ValuationPanel } from "@/components/research/ValuationPanel";
import { ReportCharts } from "@/components/charts/ReportCharts";
import { ContentKindBadge } from "@/components/ui/Badges";
import { Disclaimer, ModeBanners } from "@/components/ui/Banners";
import { Card, SectionHeading } from "@/components/ui/Layout";
import { ErrorState, SkeletonLines } from "@/components/ui/States";

export function ReportView({ sessionId }: { sessionId: string }) {
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [detail, setDetail] = useState<ResearchDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const reportRes = await getReport(sessionId);
      setReport(reportRes);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the report.");
    } finally {
      setLoading(false);
    }
    try {
      setDetail(await getResearch(sessionId));
    } catch {
      // The run header falls back to report.company / a "completed" status if this fails.
    }
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  const citationIndex = useMemo(() => {
    if (!report) return new Map<string, number>();
    const texts = report.sections.flatMap((s) => s.paragraphs.map((p) => p.text));
    return buildCitationOrder(texts);
  }, [report]);

  const knownEvidenceIds = useMemo(() => new Set(report ? Object.keys(report.citations) : []), [report]);

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonLines count={6} />
      </div>
    );
  }

  if (error || !report) {
    return (
      <ErrorState
        message={error ?? "This report is not available yet — it may still be in progress or awaiting approval."}
        onRetry={load}
      />
    );
  }

  const selectedCitation: Citation | null = selectedEvidenceId ? (report.citations[selectedEvidenceId] ?? null) : null;
  const selectedIndex = selectedEvidenceId ? citationIndex.get(selectedEvidenceId) : undefined;

  return (
    <div>
      <RunHeader
        id={sessionId}
        company={report.company}
        status={detail?.status ?? "completed"}
        query={detail?.request.query}
      />
      <ModeBanners llmMode={report.llm_mode} usesSnapshotData={report.uses_snapshot_data} />

      <div className="no-print mb-4 flex justify-end">
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded-md border border-ink-600 px-3 py-1.5 text-sm font-medium text-ink-100 transition hover:bg-ink-800"
        >
          Print / Save PDF
        </button>
      </div>

      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-ink-50">{report.title}</h1>
        <p className="mt-1 text-sm text-ink-400">
          Generated {formatDateTime(report.generated_at)} · Version {report.version}
          {report.critic_rounds > 0 &&
            ` · ${report.critic_rounds} critic revision round${report.critic_rounds === 1 ? "" : "s"}`}
          {report.unverified_claims > 0 &&
            ` · ${report.unverified_claims} unverified claim${report.unverified_claims === 1 ? "" : "s"}`}
        </p>
      </div>

      <div className="mb-8 space-y-6">
        {report.sections.length === 0 ? (
          <Card>
            <p className="text-sm text-ink-400">This report has no sections yet.</p>
          </Card>
        ) : (
          report.sections.map((section) => (
            <Card key={section.section} className="print-break-before">
              <SectionHeading>{section.title}</SectionHeading>
              <div className="space-y-3">
                {section.paragraphs.length === 0 ? (
                  <p className="text-sm text-ink-500">No content generated for this section.</p>
                ) : (
                  section.paragraphs.map((p, i) => (
                    <p key={i} className="text-sm leading-relaxed text-ink-200">
                      <ContentKindBadge kind={p.kind} unverified={p.unverified} />{" "}
                      <CitationText
                        text={p.text}
                        citationIndex={citationIndex}
                        knownEvidenceIds={knownEvidenceIds}
                        onCite={setSelectedEvidenceId}
                      />
                    </p>
                  ))
                )}
              </div>
            </Card>
          ))
        )}
      </div>

      <div className="mb-8 space-y-6">
        <Card>
          <SectionHeading>Key metrics</SectionHeading>
          <MetricsTable rows={report.key_metrics} />
        </Card>
        <Card>
          <SectionHeading>Peer comparison</SectionHeading>
          <PeerTable peers={report.peers} />
        </Card>
        <Card>
          <SectionHeading>Valuation</SectionHeading>
          <ValuationPanel valuation={report.valuation} />
        </Card>
        <Card className="print-break-before">
          <SectionHeading>Charts</SectionHeading>
          <ReportCharts charts={report.charts} peers={report.peers} />
        </Card>
      </div>

      <Disclaimer text={report.disclaimer} />

      <CitationDrawer citation={selectedCitation} index={selectedIndex} onClose={() => setSelectedEvidenceId(null)} />
    </div>
  );
}
