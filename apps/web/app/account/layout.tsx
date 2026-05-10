import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/lib/providers";

// /account/* pages are unauthenticated entry points reached from
// onboarding / password-reset emails. They share the same provider
// stack (QueryClientProvider + Toaster) as /sign-in. The root layout
// intentionally omits providers so marketing pages stay zero-JS;
// each authed entry-tree wraps its own subtree.
export const metadata: Metadata = {
  title: { absolute: "Account — CaseOps" },
  description: "Set up or reset your CaseOps account.",
  robots: { index: false, follow: false },
};

export default function AccountLayout({ children }: { children: ReactNode }) {
  return <AppProviders>{children}</AppProviders>;
}
