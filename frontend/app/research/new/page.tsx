"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, createResearch } from "@/lib/api";
import type { CompanyIdentity, Depth } from "@/lib/types";
import { PageHeader } from "@/components/ui/Layout";
import { CompanySearchInput } from "@/components/research/CompanySearchInput";

const DEPTH_OPTIONS: { value: Depth; label: string; description: string }[] = [
  { value: "quick", label: "Quick", description: "Fastest pass — wave 1 specialists only where possible." },
  { value: "standard", label: "Standard", description: "Full specialist coverage plus valuation and risk." },
  { value: "deep", label: "Deep", description: "Adds the bull/bear debate and deeper competitor analysis." },
];

export default function NewResearchPage() {
  const router = useRouter();
  const [company, setCompany] = useState<CompanyIdentity | null>(null);
  const [query, setQuery] = useState("");
  const [depth, setDepth] = useState<Depth>("standard");
  const [focusInput, setFocusInput] = useState("");
  const [focusAreas, setFocusAreas] = useState<string[]>([]);
  const [requireApproval, setRequireApproval] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function addFocusArea() {
    const trimmed = focusInput.trim();
    if (trimmed && !focusAreas.includes(trimmed) && focusAreas.length < 10) {
      setFocusAreas((prev) => [...prev, trimmed]);
      setFocusInput("");
    }
  }

  function removeFocusArea(area: string) {
    setFocusAreas((prev) => prev.filter((a) => a !== area));
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (query.trim().length < 2) {
      setError("Describe what you'd like researched (at least 2 characters).");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createResearch({
        query: query.trim(),
        ticker: company?.ticker ?? null,
        focus_areas: focusAreas,
        depth,
        require_approval: requireApproval,
        user_id: null,
      });
      router.push(`/research/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start this research run.");
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="New Research" subtitle="Describe what you want Meridian's agents to investigate." />
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* The request is the primary input and comes first. The company picker used to sit above it,
            wider and unlabelled as optional, so people typed their whole request into the picker and
            left the actual request empty. */}
        <div>
          <label htmlFor="research-query" className="mb-1 block text-sm font-medium text-ink-200">
            What should we research?
          </label>
          <textarea
            id="research-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={4}
            autoFocus
            placeholder="Analyse NVIDIA with particular attention to AI infrastructure growth, margins and valuation."
            required
            minLength={2}
            maxLength={2000}
            className="w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500"
          />
          <p className="mt-1 text-xs text-ink-400">
            Plain English is fine. The company is identified from what you write — you only need the field
            below if the name is ambiguous.
          </p>
        </div>

        <div>
          <CompanySearchInput onSelect={setCompany} />
          {company && (
            <p className="mt-1 text-xs text-ink-400">
              Pinned to {company.name} ({company.ticker}).
            </p>
          )}
        </div>

        <div>
          <span className="mb-1 block text-sm font-medium text-ink-200">Depth</span>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {DEPTH_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setDepth(opt.value)}
                aria-pressed={depth === opt.value}
                className={`rounded-md border p-3 text-left text-sm transition ${
                  depth === opt.value ? "border-accent-500 bg-accent-600/10" : "border-ink-600 hover:border-ink-500"
                }`}
              >
                <span className="block font-medium text-ink-100">{opt.label}</span>
                <span className="block text-xs text-ink-400">{opt.description}</span>
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="focus-area-input" className="mb-1 block text-sm font-medium text-ink-200">
            Focus areas <span className="font-normal text-ink-500">(optional)</span>
          </label>
          <div className="flex gap-2">
            <input
              id="focus-area-input"
              value={focusInput}
              onChange={(e) => setFocusInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addFocusArea();
                }
              }}
              placeholder="e.g. margins, AI infrastructure"
              className="flex-1 rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500"
            />
            <button
              type="button"
              onClick={addFocusArea}
              className="rounded-md border border-ink-600 px-3 py-2 text-sm font-medium text-ink-100 transition hover:bg-ink-800"
            >
              Add
            </button>
          </div>
          {focusAreas.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {focusAreas.map((area) => (
                <span
                  key={area}
                  className="inline-flex items-center gap-1 rounded-full border border-ink-600 bg-ink-800 px-2.5 py-1 text-xs text-ink-200"
                >
                  {area}
                  <button
                    type="button"
                    onClick={() => removeFocusArea(area)}
                    aria-label={`Remove ${area}`}
                    className="text-ink-400 hover:text-ink-100"
                  >
                    &times;
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        <label className="flex items-start gap-2 text-sm text-ink-200">
          <input
            type="checkbox"
            checked={requireApproval}
            onChange={(e) => setRequireApproval(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-ink-600 bg-ink-900 text-accent-600 focus:ring-accent-500"
          />
          Require my approval before the report is written
        </label>

        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-accent-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent-500 disabled:opacity-50"
        >
          {submitting ? "Starting research…" : "Start research"}
        </button>
      </form>
    </div>
  );
}
