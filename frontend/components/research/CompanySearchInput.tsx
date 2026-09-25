"use client";

import { useEffect, useState } from "react";
import { ApiError, searchCompanies } from "@/lib/api";
import { useDebouncedValue } from "@/components/hooks/useDebouncedValue";
import type { CompanyIdentity } from "@/lib/types";

interface CompanySearchInputProps {
  onSelect: (company: CompanyIdentity) => void;
}

/** Debounced company search against `GET /companies/search?q=`. */
export function CompanySearchInput({ onSelect }: CompanySearchInputProps) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 300);
  const [results, setResults] = useState<CompanyIdentity[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const trimmed = debounced.trim();
    if (trimmed.length < 2) {
      setResults([]);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    searchCompanies(trimmed)
      .then((res) => {
        if (!cancelled) setResults(res.results);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResults([]);
        setError(err instanceof ApiError ? err.message : "Company search failed.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced]);

  return (
    <div className="relative">
      <label htmlFor="company-search" className="mb-1 block text-sm font-medium text-ink-200">
        Company <span className="font-normal text-ink-500">(optional — helps resolve an ambiguous query)</span>
      </label>
      <input
        id="company-search"
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search by ticker or company name, e.g. NVDA"
        autoComplete="off"
        className="w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500"
      />
      {open && query.trim().length >= 2 && (
        <div className="absolute z-10 mt-1 w-full rounded-md border border-ink-700 bg-ink-900 shadow-lg">
          {loading && <p className="p-2 text-sm text-ink-400">Searching…</p>}
          {error && <p className="p-2 text-sm text-red-400">{error}</p>}
          {!loading && !error && results.length === 0 && <p className="p-2 text-sm text-ink-400">No matches.</p>}
          {!loading && results.length > 0 && (
            <ul>
              {results.map((company) => (
                <li key={company.cik}>
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      onSelect(company);
                      setQuery(`${company.name} (${company.ticker})`);
                      setOpen(false);
                    }}
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-ink-800"
                  >
                    <span className="font-medium text-ink-100">{company.name}</span>
                    <span className="ml-2 text-ink-400">{company.ticker}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
