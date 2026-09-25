import { NextRequest } from "next/server";

/**
 * Server-side proxy to the Meridian FastAPI backend. This is the ONLY place the backend API key is
 * used: it is read from the server-only env var `MERIDIAN_API_KEY` and injected as `X-API-Key` on every
 * upstream request. The browser only ever talks to this route (same origin, no key involved).
 *
 * The response body is streamed straight through with `new Response(upstream.body, ...)` — no buffering,
 * no re-parsing — which is required for the SSE progress stream (`GET /research/{id}/events`) to work,
 * and is harmless (just as fast) for ordinary JSON responses.
 */

export const dynamic = "force-dynamic";

const DEFAULT_BACKEND_BASE_URL = "http://localhost:8000";

function backendBaseUrl(): string {
  return (process.env.MERIDIAN_API_BASE_URL ?? DEFAULT_BACKEND_BASE_URL).replace(/\/+$/, "");
}

// Headers that must never be forwarded verbatim: either they describe this hop specifically
// (host/connection/content-length), or they are how a client might otherwise smuggle its own value for
// something only this server is trusted to set (x-api-key).
const STRIPPED_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "accept-encoding",
  "x-api-key",
]);

const STRIPPED_RESPONSE_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "keep-alive",
]);

function errorResponse(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message, details: {} } }, { status });
}

async function proxy(request: NextRequest, pathSegments: string[]): Promise<Response> {
  if (pathSegments.length === 0) {
    return errorResponse(404, "not_found", "No backend path specified.");
  }

  const target = new URL(`/api/v1/${pathSegments.map(encodeURIComponent).join("/")}`, backendBaseUrl());
  target.search = request.nextUrl.search;

  const forwardedHeaders = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) forwardedHeaders.set(key, value);
  });

  const apiKey = process.env.MERIDIAN_API_KEY;
  if (apiKey) forwardedHeaders.set("X-API-Key", apiKey);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const body = hasBody ? await request.text() : undefined;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: forwardedHeaders,
      body,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return errorResponse(502, "upstream_unreachable", "Could not reach the Meridian backend service.");
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase())) responseHeaders.set(key, value);
  });
  if (!responseHeaders.has("cache-control")) responseHeaders.set("cache-control", "no-store");

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PUT(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function DELETE(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path);
}
