import type { Metadata } from "next";
import type { ReactNode } from "react";

import { PlatformSessionProvider } from "@/lib/platform/session";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export const metadata: Metadata = {
  title: { default: "Platform reports - CaseOps", template: "%s - CaseOps" },
  description: "CaseOps platform administration.",
  robots: { index: false, follow: false, noarchive: true },
  referrer: "no-referrer",
  alternates: { canonical: null },
};

export default function PlatformLayout({ children }: { children: ReactNode }) {
  return <PlatformSessionProvider><div className="min-h-screen min-w-0 bg-[var(--color-bg)] text-[var(--color-ink)]">{children}</div></PlatformSessionProvider>;
}
