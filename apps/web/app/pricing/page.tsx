import type { Metadata } from "next";

import { PricingPageClient } from "./PricingPageClient";

export const metadata: Metadata = {
  title: "Pricing for Indian legal teams",
  description:
    "Explore CaseOps plans for solo advocates, law firms, and in-house legal teams in India. Compare current plan limits and request assisted activation.",
  alternates: { canonical: "/pricing" },
};

export default function PricingPage() {
  return <PricingPageClient />;
}
