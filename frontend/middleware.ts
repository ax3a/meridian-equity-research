import { NextRequest, NextResponse } from "next/server";

/**
 * Per-request Content-Security-Policy with a nonce.
 *
 * Next.js injects inline bootstrap scripts to hydrate the App Router, so a policy of plain
 * `script-src 'self'` blocks them and the app renders a blank page — which is exactly what the
 * production container did. The fix is a nonce rather than `unsafe-inline`: Next.js reads the nonce
 * from the request's CSP header and stamps it onto the scripts it emits, so inline execution stays
 * restricted to scripts this server actually generated.
 *
 * `strict-dynamic` lets those nonced scripts load the application's own chunks without having to
 * enumerate them. Development additionally needs `unsafe-eval` for React Fast Refresh and a websocket
 * connection for hot reload; neither is present in a production build.
 */

const isDev = process.env.NODE_ENV !== "production";

function buildCsp(nonce: string): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // Tailwind's base layer and chart colours set inline style attributes.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    isDev ? "connect-src 'self' ws: wss:" : "connect-src 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

export function middleware(request: NextRequest): NextResponse {
  const nonce = crypto.randomUUID().replace(/-/g, "");
  const csp = buildCsp(nonce);

  // Next.js looks for the nonce on the *request* CSP header when rendering.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    // Everything except static assets and the image optimiser, which need no CSP of their own.
    {
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
