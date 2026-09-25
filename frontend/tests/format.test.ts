import { describe, expect, it } from "vitest";
import {
  NULL_PLACEHOLDER,
  formatByUnit,
  formatCurrency,
  formatDate,
  formatDateTime,
  formatDuration,
  formatLargeNumber,
  formatMultiple,
  formatNumber,
  formatPercent,
  formatPerShare,
  formatRelativeTime,
  humanizeEnum,
} from "@/lib/format";

describe("null handling", () => {
  it.each([
    ["formatLargeNumber", formatLargeNumber],
    ["formatCurrency", formatCurrency],
    ["formatPerShare", formatPerShare],
    ["formatPercent", formatPercent],
    ["formatMultiple", formatMultiple],
    ["formatNumber", formatNumber],
  ])("%s renders null, undefined and NaN as the placeholder", (_name, fn) => {
    expect(fn(null)).toBe(NULL_PLACEHOLDER);
    expect(fn(undefined)).toBe(NULL_PLACEHOLDER);
    expect(fn(Number.NaN)).toBe(NULL_PLACEHOLDER);
  });

  it("formatDate and formatDateTime render null/undefined/invalid strings as the placeholder", () => {
    expect(formatDate(null)).toBe(NULL_PLACEHOLDER);
    expect(formatDate(undefined)).toBe(NULL_PLACEHOLDER);
    expect(formatDate("not-a-date")).toBe(NULL_PLACEHOLDER);
    expect(formatDateTime(null)).toBe(NULL_PLACEHOLDER);
    expect(formatDateTime("garbage")).toBe(NULL_PLACEHOLDER);
  });

  it("formatByUnit renders null as the placeholder regardless of unit", () => {
    expect(formatByUnit(null, "USD")).toBe(NULL_PLACEHOLDER);
    expect(formatByUnit(null, "ratio")).toBe(NULL_PLACEHOLDER);
    expect(formatByUnit(undefined, "x")).toBe(NULL_PLACEHOLDER);
  });

  it("formatDuration renders null/negative as the placeholder", () => {
    expect(formatDuration(null)).toBe(NULL_PLACEHOLDER);
    expect(formatDuration(-5)).toBe(NULL_PLACEHOLDER);
  });

  it("humanizeEnum renders null/undefined/empty as the placeholder", () => {
    expect(humanizeEnum(null)).toBe(NULL_PLACEHOLDER);
    expect(humanizeEnum(undefined)).toBe(NULL_PLACEHOLDER);
    expect(humanizeEnum("")).toBe(NULL_PLACEHOLDER);
  });
});

describe("formatLargeNumber", () => {
  it("abbreviates using MSFT-scale real figures from the implementation plan's fixture", () => {
    expect(formatLargeNumber(245_122_000_000)).toBe("245.1B");
    expect(formatLargeNumber(88_136_000_000)).toBe("88.1B");
    expect(formatLargeNumber(1_500)).toBe("1.5K");
    expect(formatLargeNumber(500)).toBe("500.0");
  });

  it("preserves the sign for negative magnitudes", () => {
    expect(formatLargeNumber(-4_200_000)).toBe("-4.2M");
  });
});

describe("formatCurrency", () => {
  it("formats a compact USD amount with a leading dollar sign", () => {
    expect(formatCurrency(245_122_000_000)).toBe("$245.1B");
    expect(formatCurrency(-4_200_000)).toBe("-$4.2M");
  });

  it("formats a non-compact USD amount with standard grouping", () => {
    expect(formatCurrency(1234.5, { compact: false, decimals: 2 })).toBe("$1,234.50");
  });
});

describe("formatPerShare", () => {
  it("formats a per-share value to two decimals by default", () => {
    expect(formatPerShare(11.8)).toBe("$11.80");
  });
});

describe("formatPercent", () => {
  it("converts a decimal fraction to a percentage string", () => {
    // FY2024 revenue growth from the implementation plan's MSFT fixture: 0.15675 -> "15.7%"
    expect(formatPercent(0.15675)).toBe("15.7%");
    expect(formatPercent(0.69764)).toBe("69.8%");
  });

  it("handles negative and zero fractions", () => {
    expect(formatPercent(-0.05)).toBe("-5.0%");
    expect(formatPercent(0)).toBe("0.0%");
  });
});

describe("formatMultiple", () => {
  it("appends an x suffix", () => {
    expect(formatMultiple(12.375)).toBe("12.4x");
    expect(formatMultiple(0)).toBe("0.0x");
  });
});

describe("formatNumber", () => {
  it("formats with thousands separators and fixed decimals", () => {
    expect(formatNumber(1234.5)).toBe("1,234.50");
    expect(formatNumber(1234.56, 1)).toBe("1,234.6");
  });
});

describe("formatByUnit", () => {
  it("dispatches to the right formatter per MetricUnit", () => {
    expect(formatByUnit(245_122_000_000, "USD")).toBe("$245.1B");
    expect(formatByUnit(11.8, "USD/share")).toBe("$11.80");
    expect(formatByUnit(0.25, "ratio")).toBe("25.0%");
    expect(formatByUnit(0.25, "percent")).toBe("25.0%");
    expect(formatByUnit(12.4, "x")).toBe("12.4x");
    expect(formatByUnit(5, "years")).toBe("5.0 yr");
  });
});

describe("formatRelativeTime", () => {
  it("renders coarse relative buckets relative to a fixed 'now'", () => {
    const now = new Date("2026-09-24T12:00:00Z");
    expect(formatRelativeTime("2026-09-24T11:59:58Z", now)).toBe("just now");
    expect(formatRelativeTime("2026-09-24T11:59:30Z", now)).toBe("30s ago");
    expect(formatRelativeTime("2026-09-24T11:55:00Z", now)).toBe("5m ago");
    expect(formatRelativeTime("2026-09-24T09:00:00Z", now)).toBe("3h ago");
    expect(formatRelativeTime("2026-09-20T12:00:00Z", now)).toBe("4d ago");
  });

  it("falls back to a formatted date past 30 days", () => {
    const now = new Date("2026-09-24T12:00:00Z");
    expect(formatRelativeTime("2026-01-01T00:00:00Z", now)).toBe(formatDate("2026-01-01T00:00:00Z"));
  });
});

describe("formatDuration", () => {
  it("formats sub-second, second and minute-scale durations", () => {
    expect(formatDuration(250)).toBe("250ms");
    expect(formatDuration(1500)).toBe("1.5s");
    expect(formatDuration(65_000)).toBe("1m 5s");
  });
});

describe("humanizeEnum", () => {
  it("title-cases a snake_case value", () => {
    expect(humanizeEnum("awaiting_approval")).toBe("Awaiting Approval");
    expect(humanizeEnum("fact")).toBe("Fact");
  });
});
