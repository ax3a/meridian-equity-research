"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getPreferences, getSystemStatus, updatePreferences } from "@/lib/api";
import type { ReportLength, SystemStatus, UserPreferences, ValuationMethod } from "@/lib/types";
import { PageHeader, Card, SectionHeading } from "@/components/ui/Layout";
import { ErrorState, SkeletonCard } from "@/components/ui/States";
import { humanizeEnum } from "@/lib/format";

const REPORT_LENGTHS: ReportLength[] = ["brief", "standard", "detailed"];
const VALUATION_METHODS: { value: ValuationMethod; label: string }[] = [
  { value: "pe", label: "P/E" },
  { value: "ev_ebitda", label: "EV/EBITDA" },
  { value: "ev_sales", label: "EV/Sales" },
  { value: "price_sales", label: "Price/Sales" },
  { value: "price_fcf", label: "Price/FCF" },
  { value: "dcf", label: "Discounted Cash Flow" },
];

function TagInput({
  label,
  values,
  onChange,
  placeholder,
  max,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder: string;
  max: number;
}) {
  const [input, setInput] = useState("");

  function add() {
    const trimmed = input.trim();
    if (trimmed && !values.includes(trimmed) && values.length < max) {
      onChange([...values, trimmed]);
      setInput("");
    }
  }

  return (
    <div>
      <span className="mb-1 block text-sm font-medium text-ink-200">{label}</span>
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500"
        />
        <button
          type="button"
          onClick={add}
          className="rounded-md border border-ink-600 px-3 py-2 text-sm font-medium text-ink-100 transition hover:bg-ink-800"
        >
          Add
        </button>
      </div>
      {values.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {values.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1 rounded-full border border-ink-600 bg-ink-800 px-2.5 py-1 text-xs text-ink-200"
            >
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                aria-label={`Remove ${v}`}
                className="text-ink-400 hover:text-ink-100"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([getPreferences(), getSystemStatus()])
      .then(([p, s]) => {
        setPrefs(p);
        setSystem(s);
      })
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load settings."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave() {
    if (!prefs) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await updatePreferences(prefs);
      setPrefs(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your preferences.");
    } finally {
      setSaving(false);
    }
  }

  function toggleValuationMethod(method: ValuationMethod) {
    if (!prefs) return;
    const has = prefs.valuation_methods.includes(method);
    setPrefs({
      ...prefs,
      valuation_methods: has ? prefs.valuation_methods.filter((m) => m !== method) : [...prefs.valuation_methods, method],
    });
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Settings" subtitle="Preferences for future research runs, and current system status." />

      {loading && (
        <div className="space-y-4">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {!loading && error && !prefs && <ErrorState message={error} onRetry={load} />}

      {!loading && prefs && (
        <div className="space-y-6">
          <Card>
            <SectionHeading>Report preferences</SectionHeading>
            <div className="space-y-5">
              <div>
                <label htmlFor="report-length" className="mb-1 block text-sm font-medium text-ink-200">
                  Report length
                </label>
                <select
                  id="report-length"
                  value={prefs.report_length}
                  onChange={(e) => setPrefs({ ...prefs, report_length: e.target.value as ReportLength })}
                  className="rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-ink-100"
                >
                  {REPORT_LENGTHS.map((len) => (
                    <option key={len} value={len}>
                      {humanizeEnum(len)}
                    </option>
                  ))}
                </select>
              </div>

              <TagInput
                label="Preferred sectors"
                values={prefs.preferred_sectors}
                onChange={(v) => setPrefs({ ...prefs, preferred_sectors: v })}
                placeholder="e.g. Semiconductors"
                max={20}
              />

              <TagInput
                label="Preferred metrics"
                values={prefs.preferred_metrics}
                onChange={(v) => setPrefs({ ...prefs, preferred_metrics: v })}
                placeholder="e.g. free_cash_flow"
                max={30}
              />

              <div>
                <span className="mb-1 block text-sm font-medium text-ink-200">Valuation methods</span>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {VALUATION_METHODS.map((m) => (
                    <label key={m.value} className="flex items-center gap-2 text-sm text-ink-200">
                      <input
                        type="checkbox"
                        checked={prefs.valuation_methods.includes(m.value)}
                        onChange={() => toggleValuationMethod(m.value)}
                        className="h-4 w-4 rounded border-ink-600 bg-ink-900 text-accent-600 focus:ring-accent-500"
                      />
                      {m.label}
                    </label>
                  ))}
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm text-ink-200">
                <input
                  type="checkbox"
                  checked={prefs.require_approval}
                  onChange={(e) => setPrefs({ ...prefs, require_approval: e.target.checked })}
                  className="h-4 w-4 rounded border-ink-600 bg-ink-900 text-accent-600 focus:ring-accent-500"
                />
                Require my approval before the report is written, by default
              </label>

              {error && (
                <p role="alert" className="text-sm text-red-400">
                  {error}
                </p>
              )}
              {saved && <p className="text-sm text-emerald-400">Preferences saved.</p>}

              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="rounded-md bg-accent-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-500 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save preferences"}
              </button>
            </div>
          </Card>

          {system && (
            <Card>
              <SectionHeading>System & providers</SectionHeading>
              <dl className="mb-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-xs text-ink-400">Version</dt>
                  <dd className="text-ink-100">{system.version}</dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-400">LLM mode</dt>
                  <dd className="text-ink-100">{humanizeEnum(system.llm_mode)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-400">Data mode</dt>
                  <dd className="text-ink-100">{humanizeEnum(system.data_mode)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-400">Active runs</dt>
                  <dd className="text-ink-100">{system.active_runs}</dd>
                </div>
              </dl>
              <ul className="space-y-1 text-sm">
                {system.providers.map((p) => (
                  <li key={p.name} className="flex items-center justify-between gap-2 border-t border-ink-800 py-1.5">
                    <div>
                      <span className="text-ink-100">{p.name}</span>{" "}
                      <span className="text-xs text-ink-500">({p.role})</span>
                      {p.detail && <p className="text-xs text-ink-500">{p.detail}</p>}
                    </div>
                    <span className={p.configured ? "text-xs text-emerald-400" : "text-xs text-ink-500"}>
                      {p.configured ? "Ready" : "Not configured"}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
