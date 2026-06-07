import { NextResponse } from "next/server";

import { siteConfig } from "@/lib/site";

// The /llms.txt convention (llmstxt.org): a small, human-curated
// guide telling LLM crawlers what the site is about, where the
// canonical content lives, and which deep pages they should prefer.

const body = `# CaseOps - Indian legal operating system

> CaseOps is a matter-native legal operating system for Indian law firms and corporate legal teams. It unifies matter management, drafting, hearing preparation, tracked case refresh, court-order compliance review, cause-list PDFs, contracts, outside counsel, and India-ready matter billing into a single citation-grounded workspace.

- Home: ${siteConfig.url}
- User guide: ${siteConfig.url}/guide
- Tagline: ${siteConfig.tagline}
- Primary jurisdictions: Supreme Court of India, High Courts, lower courts, tribunals, and forums where lawful source access and source-quality proof exist
- Built around Indian statute names (BNS, BNSS, BSA, CrPC, CPC) - not retrofitted from a US product
- Grounding: every substantive legal answer is backed by a citation from an indexed authority or source document; no fabricated case law

## What the product does

- **Matter management**: intake, matter workspaces, documents, hearings, tasks, notes, Dispose status, next-hearing provenance, ethical walls, and audit
- **Case tracking**: explicitly tracked/bookmarked cases refresh in the configured 4 PM-6 PM IST window; disabled or misconfigured providers make no external calls and record blocked/skipped state
- **Court-order compliance**: deterministic extraction first, AI only when tenant policy allows, schema validation, source snippets, confidence labels, review-required compliance items, and lawyer confirmation before activation by default
- **Cause lists**: date-wise preview and server-rendered PDF with serial number, file number, court, case number, case title, judge, court number, item number, lawyers appearing, hearing date, missing-field warnings, overrides, and download audit
- **Drafting**: bail applications, quashing petitions, civil reviews, arbitration submissions, and more with no invented facts, no invented authorities, and statute-guidance-aware BNS vs BNSS
- **Hearing prep**: structured packs with chronology, last order, pending compliance, issues, opposition points, authority cards, and oral-submission notes
- **Research**: multi-tenant authority corpus, structured extraction, reranking, and tenant-private annotations
- **Outside counsel**: panel management, spend logging, and counsel recommendations per matter
- **Matter billing**: law-firm billing profiles, rates, fixed fees, milestones, expenses, retainers/advances, firm/client GST fields, place of supply, SAC/HSN/service classification, CGST/SGST/IGST split, TDS adjustments, amount paid/outstanding, and server-rendered invoice PDFs

## Safety limits

- CaseOps does not bypass captcha, login, or session-gated court sources.
- CaseOps does not make unapproved external provider calls.
- Email, SMS, and WhatsApp are not sent unless an approved delivery provider is explicitly configured; otherwise durable in-app notification intents are used.
- Tenant-facing surfaces do not expose provider tokens, raw provider payloads, raw prompts, raw LLM responses, internal costs, or unauthorized tenant-private data.
- Customer data is not used for cross-tenant training by default.

## Contact

- ${siteConfig.contact.email}
- Sign-in / try the product: ${siteConfig.url}/sign-in
`;

export function GET() {
  return new NextResponse(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=3600",
    },
  });
}
