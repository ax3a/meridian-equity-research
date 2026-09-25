import type { NextConfig } from "next";

/**
 * Content-Security-Policy: in production, no `unsafe-eval` and no inline scripts — scripts are
 * restricted to `self` (Next.js's own hashed bundles). `unsafe-inline` is permitted only for styles,
 * because Tailwind's base layer and some chart colours use inline `style` attributes.
 *
 * Development needs `unsafe-eval` and `unsafe-inline` for scripts: `next dev` injects inline bootstrap
 * scripts and React Fast Refresh evaluates code as strings. Without this relaxation the dev server
 * renders an empty shell whose data never loads, while the production build works fine — so the
 * exception is scoped to NODE_ENV !== "production" and never ships.
 */
const isDev = process.env.NODE_ENV !== "production";

const CSP = [
  "default-src 'self'",
  isDev ? "script-src 'self' 'unsafe-eval' 'unsafe-inline'" : "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  // Dev also opens a websocket back to the dev server for hot reload.
  isDev ? "connect-src 'self' ws: wss:" : "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone output produces a self-contained server bundle (`.next/standalone`) that the
  // production Docker image runs directly with `node server.js`, without needing `node_modules`
  // or the rest of the workspace copied into the runtime image.
  output: "standalone",
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
