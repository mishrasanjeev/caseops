import type { Metadata } from "next";

import { PricingPageClient } from "./PricingPageClient";

export const metadata: Metadata = {
  title: "Pricing for Indian legal teams",
  description:
    "Published INR plans for solo advocates, law firms, and in-house legal teams in India. Research, drafting, matters, and court tracking in every plan, with a 14-day trial and no card.",
  alternates: { canonical: "/pricing" },
};

export default function PricingPage() {
  return <PricingPageClient />;
}
