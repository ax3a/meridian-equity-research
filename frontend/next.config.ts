import type { NextConfig } from "next";

/**
 * Content-Security-Policy: no `unsafe-eval`; `unsafe-inline` is permitted only for styles because
 * Tailwind's base layer and a handful of components use inline `style` attributes for chart colours.
 * Scripts are restricted to `self` (Next.js's own hashed bundles) with no inline execution allowed.
 */
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'self'",
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
