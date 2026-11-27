import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/lib/providers";

// ENH-001: public landing for the QR code printed on billing PDFs. Each link
// is a per-document secret, so the pages are never indexed.
export const metadata: Metadata = {
  title: { absolute: "Verify a billing document — CaseOps" },
  description: "Confirm the issuer, status and fingerprint of a CaseOps billing document.",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function VerifyLayout({ children }: { children: ReactNode }) {
  return <AppProviders>{children}</AppProviders>;
}
