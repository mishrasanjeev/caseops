import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/lib/providers";

export const metadata: Metadata = {
  title: { absolute: "Sign in — CaseOps" },
  description: "Sign in to your CaseOps workspace.",
  robots: { index: false, follow: false },
};

export default function SignInLayout({ children }: { children: ReactNode }) {
  return <AppProviders>{children}</AppProviders>;
}
