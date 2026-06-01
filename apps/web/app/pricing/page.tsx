import type { Metadata } from "next";

import { PricingPageClient } from "./PricingPageClient";

export const metadata: Metadata = {
  title: "Pricing - CaseOps",
  description:
    "CaseOps pricing for solo lawyers, law firms, and corporate legal teams.",
  alternates: { canonical: "/pricing" },
};

export default function PricingPage() {
  return <PricingPageClient />;
}
