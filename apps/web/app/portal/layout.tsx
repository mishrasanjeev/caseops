import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/lib/providers";

export const metadata: Metadata = {
  title: { absolute: "Workspace portal — CaseOps" },
  description:
    "Secure portal for clients and outside counsel. Magic-link sign-in.",
  robots: { index: false, follow: false },
};

export default function PortalLayout({ children }: { children: ReactNode }) {
  return <AppProviders>{children}</AppProviders>;
}
