/**
 * Formatting helpers for currency, percentages, large numbers, multiples and dates. Every function is
 * null-safe: `null` / `undefined` / `NaN` always render as the placeholder dash rather than throwing or
 * printing "NaN" / "null" in the UI.
 */

export const NULL_PLACEHOLDER = "—"; // em dash

type Nullish = number | null | undefined;

function isUsable(value: Nullish): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Abbreviate a raw magnitude with K/M/B/T suffixes, e.g. 245122000000 -> "245.1B". */
export function formatLargeNumber(value: Nullish, decimals = 1): string {
  if (!isUsable(value)) return NULL_PLACEHOLDER;
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(decimals)}T`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(decimals)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(decimals)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(decimals)}K`;
  return `${sign}${abs.toFixed(decimals)}`;
}

/** Format a raw USD amount, e.g. 245122000000 -> "$245.1B", -4200000 -> "-$4.2M". */
export function formatCurrency(value: Nullish, opts?: { decimals?: number; compact?: boolean }): string {
  if (!isUsable(value)) return NULL_PLACEHOLDER;
  const decimals = opts?.decimals ?? 1;
  const compact = opts?.compact ?? true;
  if (compact) {
    const sign = value < 0 ? "-" : "";
    return `${sign}$${formatLargeNumber(Math.abs(value), decimals)}`;
  }
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Format a per-share USD value, e.g. 11.8 -> "$11.80". */
export function formatPerShare(value: Nullish, decimals = 2): string {
  if (!isUsable(value)) return NULL_PLACEHOLDER;
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Format a decimal ratio as a percentage, e.g. 0.15675 -> "15.7%". Input is a fraction, not already *100. */
export function formatPercent(value: Nullish, decimals = 1): string {
  if (!isUsable(value)) return NULL_PLACEHOLDER;
  return `${(value * 100).toFixed(decimals)}%`;
}

/** Format a multiple, e.g. 12.375 -> "12.4x". */
export function formatMultiple(value: Nullish, decimals = 1): string {
  if (!isUsable(value)) return NULL_PLACEHOLDER;
  return `${value.toFixed(decimals)}x`;
}

/** Plain decimal formatting with thousands separators, e.g. 1234.5 -> "1,234.50". */
export function formatNumber(value: Nullish, decimals = 2): string {
  if (!isUsable(value)) return NULL_PLACEHOLDER;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Format by `MetricUnit`/chart unit string so callers don't need a switch at every call site. */
export function formatByUnit(value: Nullish, unit: string): string {
  if (!isUsable(value)) return NULL_PLACEHOLDER;
  switch (unit) {
    case "USD":
      return formatCurrency(value);
    case "USD/share":
      return formatPerShare(value);
    case "shares":
      return formatLargeNumber(value, 2);
    case "ratio":
    case "percent":
      return formatPercent(value);
    case "x":
      return formatMultiple(value);
    case "years":
      return `${formatNumber(value, 1)} yr`;
    default:
      return formatNumber(value);
  }
}

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Format an ISO date string, e.g. "2024-06-30" -> "Jun 30, 2024". */
export function formatDate(value: string | null | undefined): string {
  const d = toDate(value);
  if (!d) return NULL_PLACEHOLDER;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

/** Format an ISO datetime string, e.g. "2026-09-24T14:03:00Z" -> "Sep 24, 2026, 2:03 PM". */
export function formatDateTime(value: string | null | undefined): string {
  const d = toDate(value);
  if (!d) return NULL_PLACEHOLDER;
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Relative time, e.g. "3m ago", "2h ago", "5d ago". Falls back to a formatted date past 30 days. */
export function formatRelativeTime(value: string | null | undefined, now: Date = new Date()): string {
  const d = toDate(value);
  if (!d) return NULL_PLACEHOLDER;
  const diffMs = now.getTime() - d.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return formatDate(value);
}

/** Duration in milliseconds -> human string, e.g. 1500 -> "1.5s", 65000 -> "1m 5s". */
export function formatDuration(ms: Nullish): string {
  if (!isUsable(ms) || ms < 0) return NULL_PLACEHOLDER;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return `${minutes}m ${seconds}s`;
}

/** Title-case a snake_case enum value for display, e.g. "awaiting_approval" -> "Awaiting Approval". */
export function humanizeEnum(value: string | null | undefined): string {
  if (!value) return NULL_PLACEHOLDER;
  return value
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
