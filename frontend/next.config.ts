import type { NextConfig } from "next";

/**
 * The Content-Security-Policy is set per request in `middleware.ts`, because Next.js needs a nonce for
 * the inline scripts it injects to hydrate the App Router. The static headers below carry everything
 * that does not vary per request.
 */

const securityHeaders = [
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
