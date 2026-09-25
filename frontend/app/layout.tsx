import type { Metadata } from "next";
import { NavBar } from "@/components/layout/NavBar";
import "./globals.css";

// Rendered per request so the CSP nonce from `middleware.ts` can be stamped onto Next.js's inline
// hydration scripts: a statically prerendered page is cached without one, and its scripts are then
// blocked by the policy, leaving a blank shell. Every page here renders live API data, so there is no
// static output worth preserving.
export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: {
    default: "Meridian Research",
    template: "%s · Meridian Research",
  },
  description:
    "Meridian is a multi-agent equity research platform: autonomous specialist agents gather evidence, " +
    "compute metrics deterministically, and write a citation-backed research report for human review.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark">
      <body className="min-h-screen bg-ink-950 font-sans text-ink-100 antialiased">
        <NavBar />
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
