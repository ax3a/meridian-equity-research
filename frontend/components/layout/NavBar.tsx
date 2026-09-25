"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/research/new", label: "New Research" },
  { href: "/settings", label: "Settings" },
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="no-print sticky top-0 z-30 border-b border-ink-700 bg-ink-950/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight text-ink-50">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent-600 text-xs font-bold text-white">
            M
          </span>
          Meridian
        </Link>
        <nav className="flex items-center gap-1" aria-label="Primary">
          {LINKS.map((link) => {
            const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                  active ? "bg-ink-800 text-ink-50" : "text-ink-300 hover:bg-ink-800/60 hover:text-ink-100"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
