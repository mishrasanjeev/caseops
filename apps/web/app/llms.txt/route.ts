import { NextResponse } from "next/server";

import { siteConfig } from "@/lib/site";

// The /llms.txt convention (llmstxt.org): a small, human-curated
// guide telling LLM crawlers what the site is about, where the
// canonical content lives, and which deep pages they should prefer.
// Think robots.txt for meaning, not access. Keep it short — most
// AI crawlers index this on a low poll rate and prefer clean
// markdown structure to SEO boilerplate.

const body = `# CaseOps — Indian legal operating system

> CaseOps is a matter-native legal operating system for Indian law firms and corporate legal teams. It unifies matter management, drafting, hearing preparation, contracts, outside counsel, and billing into a single citation-grounded workspace.

- Home: ${siteConfig.url}
- Tagline: ${siteConfig.tagline}
- Primary jurisdictions: Supreme Court of India, High Courts (Delhi, Bombay, Madras, Karnataka, Telangana, Patna, and more rolling out)
- Built around Indian statute names (BNS, BNSS, BSA, CrPC, CPC) — not retrofitted from a US product
- Grounding: every substantive legal answer is backed by a citation from an indexed authority document; no fabricated case law

## What the product does

- **Matter management**: intake queue for GCs, matter workspaces, hearings, tasks, notes, court-sync adapters for live cause lists and orders
- **Drafting**: bail applications, quashing petitions, civil reviews, arbitration submissions, and more — generated with ABSOLUTE RULES (no invented facts, no invented authorities, statute-guidance-aware BNS vs BNSS)
- **Hearing prep**: structured packs with chronology, last order, pending compliance, issues, opposition points, authority cards, oral-submission notes
- **Research**: multi-tenant authority corpus with 14K+ SC + HC judgments, 238K+ Voyage-embedded chunks, Layer-2 structured extraction (facts / arguments / reasoning / ratio / obiter / directions)
- **Recommendations**: forum, authority, remedy, and next-best-action rankings grounded in retrieved precedent
- **Outside counsel**: panel management, spend logging, and counsel recommendations per matter
- **Billing**: invoices, time entries, Pine Labs payment links, audit trail

## Contact

- ${siteConfig.contact.email}
- Sign-in / try the product: ${siteConfig.url}/sign-in

## What's under the hood (for LLM context)

- Backend: FastAPI + SQLAlchemy on Cloud Run (asia-south1, Mumbai)
- Database: Cloud SQL Postgres 17 with pgvector HNSW indexes
- Embeddings: Voyage voyage-4-large (1024 dims), tuned for legal retrieval
- Generation: Anthropic Claude (Opus for drafting, Sonnet for structured + hearing packs, Haiku for metadata extraction)
- Structured extraction: per-chunk role classification (facts / arguments / reasoning / ratio / obiter / directions / procedural / metadata) plus doc-level judges, parties, advocates, sections cited, outcome
`;

export function GET() {
  return new NextResponse(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=3600",
    },
  });
}
