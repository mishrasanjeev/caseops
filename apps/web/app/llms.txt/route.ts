import { NextResponse } from "next/server";

import { siteConfig } from "@/lib/site";

// The /llms.txt convention (llmstxt.org): a small, human-curated
// guide telling LLM crawlers what the site is about, where the
// canonical content lives, and which deep pages they should prefer.

const body = `# CaseOps - Indian legal operating system

> CaseOps is a matter-native legal operating system for Indian law firms and corporate legal teams. It unifies intake and optional conflict review, matter management, notices and reply deadlines, drafting, hearing preparation, tracked case refresh, court-order compliance review, cause-list PDFs, contracts, outside counsel, and India-ready matter billing into a single citation-grounded workspace.

- Home: ${siteConfig.url}
- User guide: ${siteConfig.url}/guide
- Tagline: ${siteConfig.tagline}
- Product owner: ${siteConfig.ownership.legalOwner}
- Inventor/Owner: ${siteConfig.ownership.inventorOwner}
- Primary jurisdictions: Supreme Court of India, High Courts, lower courts, tribunals, and forums where lawful source access and source-quality proof exist
- Built around Indian statute names (BNS, BNSS, BSA, CrPC, CPC) - not retrofitted from a US product
- Grounding: every substantive legal answer is backed by a citation from an indexed authority or source document; no fabricated case law

## What the product does

- **Matter management**: intake, matter workspaces, timeline, tasks and deadlines, documents, notices, drafts, hearings, intelligence, communications, billing, Dispose status, next-hearing provenance, server-enforced matter access, and audit
- **Conflict review**: checks are optional, auditable, and nonblocking; New Matter starts Active by default, and Intake or On hold can move to Active regardless of whether a check is absent, pending, conflicted, cleared, waived, or stale
- **Notices**: centralized /app/notices register for standalone or zero/multi-matter-linked received/sent notices, with optional owner/file, status and reply tracking, workspace filters, and clearly read-only legacy matter attachments
- **Status vocabulary**: every public claim is one of live, review-first, provider-gated, founder-only, disabled until UAT, or planned
- **Case tracking**: explicitly tracked/bookmarked cases refresh in the configured 4 PM-6 PM IST window; disabled or misconfigured providers make no external calls and record blocked/skipped state
- **Court-order compliance**: deterministic extraction first, AI only when tenant policy allows, schema validation, source snippets, confidence labels, review-required compliance items, and lawyer confirmation before activation by default
- **Cause lists**: date-wise preview and server-rendered PDF with serial number, file number, court, case number, case title, judge, court number, item number, lawyers appearing, hearing date, missing-field warnings, and download audit; incomplete rows are corrected in their source records rather than a per-row override editor
- **Drafting**: bail applications, quashing petitions, civil reviews, arbitration submissions, and more with no invented facts, no invented authorities, and statute-guidance-aware BNS vs BNSS
- **Hearing prep**: structured packs with chronology, last order, pending compliance, issues, opposition points, authority cards, and oral-submission notes
- **Research**: shared public authority corpus, structured extraction, reranking, and tenant-private workspace notebook entries
- **Judge research**: canonical judge identities and aliases, bounded mapped-judgment browsing, source actions, confidence evidence, coverage-qualified descriptive analytics, and a staff-only audited mapping-review queue; low-confidence mappings are excluded from analytics and no judge scoring or outcome forecasts are offered
- **Trademark oppositions**: distinct application/opposition identifiers, applicant and opponent TM-O work, Rules 45-47 affidavit packages, authorized deadline replacement, shared hearing preparation, sourced orders, compliance directions, and order-linked appeal records
- **IP and Matter linkage**: effective-dated operational, litigation, advisory, appeal, enforcement, billing, and other relationships; side-by-side independent lifecycle state; access-mismatch warnings; and accessible IP events referenced in Matter timelines without copied activity
- **Outside counsel**: panel profiles, matter assignments, budgets/fee arrangements, spend logging, and payment state where supported
- **Matter billing**: law-firm billing profiles, rates, fixed fees, milestones, expenses, retainers/advances, firm/client GST fields, place of supply, SAC/HSN/service classification, CGST/SGST/IGST split, TDS adjustments, amount paid/outstanding, and server-rendered invoice PDFs
- **Access recovery**: /sign-in links to /account/forgot-password for anti-enumeration reset requests; reset completion uses single-use 60-minute links and never emails raw passwords

## Safety limits

- CaseOps does not bypass captcha, login, or session-gated court sources.
- CaseOps does not make unapproved external provider calls.
- Pine Labs production payments are disabled until UAT evidence and founder go/no-go are complete.
- OIDC/SAML SSO, SCIM, private enterprise deployment, and autonomous scoped-agent execution are planned/readiness-only, not live.
- Google Workspace, Microsoft 365, inbound email, SMS, WhatsApp, and court-provider automation are provider-gated where credentials, consent, webhook signing, template/DLT approval, or legal source proof is missing.
- Email, SMS, and WhatsApp are not sent unless an approved delivery provider is explicitly configured; otherwise durable in-app notification intents are used.
- Tenant-facing surfaces do not expose provider tokens, raw provider payloads, raw prompts, raw LLM responses, internal costs, or unauthorized tenant-private data.
- Customer data is not used for cross-tenant training by default.

## Contact

- ${siteConfig.ownership.emails[0]}
- ${siteConfig.ownership.emails[1]}
- Sign-in / try the product: ${siteConfig.url}/sign-in
- Forgot password: ${siteConfig.url}/account/forgot-password
`;

export function GET() {
  return new NextResponse(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=3600",
    },
  });
}
