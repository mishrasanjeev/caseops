"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/cn";

type Tab = { href: string; label: string };

export function MatterCockpitNav({ matterId }: { matterId: string }) {
  const pathname = usePathname();
  const base = `/app/matters/${matterId}`;
  const tabs: Tab[] = [
    { href: base, label: "Overview" },
    { href: `${base}/documents`, label: "Documents" },
    { href: `${base}/hearings`, label: "Hearings" },
    { href: `${base}/recommendations`, label: "Recommendations" },
    { href: `${base}/billing`, label: "Billing" },
    { href: `${base}/audit`, label: "Audit" },
  ];

  return (
    <nav
      aria-label="Matter cockpit tabs"
      className="flex items-center gap-1 overflow-x-auto rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] p-1"
    >
      {tabs.map((tab) => {
        const active = isTabActive(pathname, tab.href, base);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex items-center whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-all",
              active
                ? "bg-white text-[var(--color-ink)] shadow-[var(--shadow-soft)]"
                : "text-[var(--color-mute)] hover:text-[var(--color-ink)]",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

function isTabActive(pathname: string | null, href: string, base: string): boolean {
  if (!pathname) return false;
  if (href === base) return pathname === base;
  return pathname === href || pathname.startsWith(`${href}/`);
}
