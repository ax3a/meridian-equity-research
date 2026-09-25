/**
 * Browser-side API client. Every call goes to this Next.js server's own `/api/proxy/*` route handler
 * (see `app/api/proxy/[...path]/route.ts`), never directly to the Meridian backend — the backend's API
 * key lives only in the proxy's server-side environment and is never sent to, or knowable by, the browser.
 */

import type {
  CompanySearchResult,
  DashboardView,
  FeedbackRequest,
  ResearchCreated,
  ResearchDetail,
  ResearchReport,
  ResearchRequest,
  ResearchSummary,
  ReviewPackage,
  SourceView,
  StatusView,
  SystemStatus,
  TraceView,
  UserPreferences,
  AgentRunView,
} from "./types";

const PROXY_BASE = "/api/proxy";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${PROXY_BASE}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the Meridian server. Check your connection.");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }

  if (!response.ok) {
    const body = parsed as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | undefined;
    throw new ApiError(
      response.status,
      body?.error?.code ?? "unknown_error",
      body?.error?.message ?? `Request failed with status ${response.status}`,
      body?.error?.details ?? {},
    );
  }

  return parsed as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const usable = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (usable.length === 0) return "";
  const search = new URLSearchParams(usable.map(([k, v]) => [k, String(v)]));
  return `?${search.toString()}`;
}

// ---------------------------------------------------------------------------
// POST /research, GET /research, GET /research/{id}...
// ---------------------------------------------------------------------------

export function createResearch(payload: ResearchRequest): Promise<ResearchCreated> {
  return request<ResearchCreated>("/research", { method: "POST", body: JSON.stringify(payload) });
}

export function listResearch(): Promise<ResearchSummary[]> {
  return request<ResearchSummary[]>("/research");
}

export function getResearch(id: string): Promise<ResearchDetail> {
  return request<ResearchDetail>(`/research/${encodeURIComponent(id)}`);
}

export function getResearchStatus(id: string): Promise<StatusView> {
  return request<StatusView>(`/research/${encodeURIComponent(id)}/status`);
}

export function getReport(id: string): Promise<ResearchReport> {
  return request<ResearchReport>(`/research/${encodeURIComponent(id)}/report`);
}

export function getAgentRuns(id: string): Promise<AgentRunView[]> {
  return request<AgentRunView[]>(`/research/${encodeURIComponent(id)}/agents`);
}

export function getSources(id: string): Promise<SourceView[]> {
  return request<SourceView[]>(`/research/${encodeURIComponent(id)}/sources`);
}

export function getTrace(id: string): Promise<TraceView> {
  return request<TraceView>(`/research/${encodeURIComponent(id)}/trace`);
}

export function getReview(id: string): Promise<ReviewPackage> {
  return request<ReviewPackage>(`/research/${encodeURIComponent(id)}/review`);
}

export function submitFeedback(id: string, body: FeedbackRequest): Promise<void> {
  return request<void>(`/research/${encodeURIComponent(id)}/feedback`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function approveResearch(id: string): Promise<void> {
  return request<void>(`/research/${encodeURIComponent(id)}/approve`, { method: "POST" });
}

export function cancelResearch(id: string): Promise<void> {
  return request<void>(`/research/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Companies, dashboard, preferences, system
// ---------------------------------------------------------------------------

export function searchCompanies(q: string): Promise<CompanySearchResult> {
  return request<CompanySearchResult>(`/companies/search${qs({ q })}`);
}

export function getDashboard(): Promise<DashboardView> {
  return request<DashboardView>("/dashboard");
}

export function getPreferences(): Promise<UserPreferences> {
  return request<UserPreferences>("/preferences");
}

export function updatePreferences(prefs: UserPreferences): Promise<UserPreferences> {
  return request<UserPreferences>("/preferences", { method: "PUT", body: JSON.stringify(prefs) });
}

export function getSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>("/system/status");
}

/** URL for the SSE progress stream, to be opened directly with `EventSource` (no headers needed). */
export function eventsUrl(id: string): string {
  return `${PROXY_BASE}/research/${encodeURIComponent(id)}/events`;
}
