import type { Metadata } from "next";
import type { ReactNode } from "react";

import { RequireAuth } from "@/components/app/RequireAuth";
import { Sidebar } from "@/components/app/Sidebar";
import { Topbar } from "@/components/app/Topbar";
import { AppProviders } from "@/lib/providers";

export const metadata: Metadata = {
  title: { absolute: "Workspace — CaseOps" },
  description: "Run matters, hearings, drafts, contracts, and billing on CaseOps.",
  robots: { index: false, follow: false },
};

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AppProviders>
      <RequireAuth>
        <div className="flex min-h-screen bg-[var(--color-bg)]">
          <Sidebar />
          <div className="flex min-h-screen flex-1 flex-col">
            <Topbar />
            <main className="flex-1 px-5 py-6 md:px-8 md:py-8">{children}</main>
          </div>
        </div>
      </RequireAuth>
    </AppProviders>
  );
}
