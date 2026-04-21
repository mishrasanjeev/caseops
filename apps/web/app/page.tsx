import type { Metadata } from "next";

import { CTA } from "@/components/marketing/CTA";
import { FAQ } from "@/components/marketing/FAQ";
import { Features } from "@/components/marketing/Features";
import { Footer } from "@/components/marketing/Footer";
import { Hero } from "@/components/marketing/Hero";
import { Nav } from "@/components/marketing/Nav";
import { Pricing } from "@/components/marketing/Pricing";
import { ProductGallery } from "@/components/marketing/ProductGallery";
import { Security } from "@/components/marketing/Security";
import { Workflows } from "@/components/marketing/Workflows";
import { SkipLink } from "@/components/ui/SkipLink";
import { siteConfig } from "@/lib/site";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: siteConfig.url,
    title: `${siteConfig.name} — ${siteConfig.tagline}`,
    description: siteConfig.description,
  },
};

const faqJsonLd = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Is CaseOps another chatbot for lawyers?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. CaseOps is a system of work. Drafting, hearing prep, research, contracts, and billing are first-class workspaces backed by a matter graph. AI is a feature of the system, not the product.",
      },
    },
    {
      "@type": "Question",
      name: "How does CaseOps avoid hallucinated citations?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Legal knowledge lives in retrieval and source systems, not the model. Every substantive answer is grounded in statutes, judgments, or your own precedents with inline citations, assumptions, missing facts, and confidence. Weak-evidence prompts return an explicit refusal.",
      },
    },
    {
      "@type": "Question",
      name: "What courts and jurisdictions are covered?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Lower courts, High Courts, and the Supreme Court are in scope from the first release. Delhi NCR, Maharashtra, Karnataka, and Telangana are priority rollouts.",
      },
    },
    {
      "@type": "Question",
      name: "How is tenant data isolated?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Every record, document, embedding, and audit event carries a tenant id and is filtered at the query and storage layer. Matter-level ethical walls override broad role access.",
      },
    },
  ],
};

export default function LandingPage() {
  return (
    <>
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />
      <SkipLink />
      <Nav />
      <main id="main" tabIndex={-1} className="focus:outline-none">
        <Hero />
        <Features />
        <ProductGallery />
        <Workflows />
        <Security />
        <Pricing />
        <FAQ />
        <CTA />
      </main>
      <Footer />
    </>
  );
}
