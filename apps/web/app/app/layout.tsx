import type { Metadata } from "next";
import type { ReactNode } from "react";

import { OfflineBanner } from "@/components/app/OfflineBanner";
import { RequireAuth } from "@/components/app/RequireAuth";
import { Sidebar } from "@/components/app/Sidebar";
import { Topbar } from "@/components/app/Topbar";
import { SkipLink } from "@/components/ui/SkipLink";
import { AppProviders } from "@/lib/providers";

export const metadata: Metadata = {
  title: { absolute: "Workspace — CaseOps" },
  description: "Run matters, hearings, drafts, contracts, and billing on CaseOps.",
  robots: { index: false, follow: false },
};

export default function AppLayout({ children }: { children: ReactNode }) {
  // BUG-012 (2026-04-24, Ram, reopened): without overflow-x-hidden on
  // the outer wrapper + min-w-0 on the inner flex column, a single
  // wide child (a long matter title, a dialog with grid-cols-2 on
  // mobile, a horizontal table) pushes the body wider than the
  // viewport and the entire app horizontally scrolls on mobile.
  // ``min-w-0`` on the inner flex column lets the column shrink
  // smaller than its content; ``overflow-x-hidden`` on the outer
  // wrapper is the belt-and-suspenders so future regressions stay
  // contained.
  return (
    <AppProviders>
      <RequireAuth>
        <SkipLink />
        <div className="flex min-h-screen overflow-x-hidden bg-[var(--color-bg)]">
          <Sidebar />
          <div className="flex min-h-screen min-w-0 flex-1 flex-col">
            <OfflineBanner />
            <Topbar />
            <main
              id="main"
              tabIndex={-1}
              className="min-w-0 flex-1 px-5 py-6 focus:outline-none md:px-8 md:py-8"
            >
              {children}
            </main>
          </div>
        </div>
      </RequireAuth>
    </AppProviders>
  );
}
