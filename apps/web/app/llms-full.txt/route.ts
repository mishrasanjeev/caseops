import { NextResponse } from "next/server";

import { siteConfig } from "@/lib/site";

// /llms-full.txt is the "full-content" companion to /llms.txt —
// LLM crawlers that support it ingest a one-shot markdown dump of
// the site's public surface so they can answer "what does CaseOps
// do?" without stitching together fragments of HTML.
//
// This is the public-marketing content. The authenticated product
// surface (/app/*) is disallowed in robots.txt and never appears
// here. If we add more public docs (blog, case studies, docs site),
// we concatenate them here.

const body = `# CaseOps — Indian Legal Operating System

${siteConfig.description}

## What CaseOps is

CaseOps is a matter-native legal operating system built for Indian legal practice — not a generic workflow tool or a retrofitted US-first product. Every surface respects the Indian statute stack (BNS, BNSS, BSA, CrPC, CPC, Arbitration Act, SRA, Companies Act), the Indian forum hierarchy (Supreme Court → High Court → District Court → Tribunals), and the Indian docketing conventions (SLP / C.A. / W.P. / Arb.P. / Comm. / FAO / RFA numbering).

The product sits next to Bloomberg Terminal and Linear in tone — dense, keyboard-first, built for lawyers and legal ops teams who run real caseloads, not a consumer SaaS chrome.

## Who it's for

- **Indian law firms** (solo to mid-size): litigation teams that need faster research, drafting, hearing prep, and billing.
- **Corporate legal / General Counsel** teams: contract review, intake triage from business stakeholders, outside-counsel panel management, compliance.
- **Litigation partners** who want AI assistance they can actually cite in court without inventing authorities.

## The core workflows it supports

### 1. Matter management
- Intake queue (GC-facing form or direct lawyer entry) → triage → matter
- Matter workspace with tabs for documents, drafts, hearings, recommendations, billing, audit trail
- Matter-level ACL and ethical walls — a partner representing party A can be locked out of party B's matter
- Team scoping (Sprint 8c) — work visible only to assigned team
- Court-sync adapters: live cause-list + recent-orders for Delhi HC, Bombay HC, Madras HC, Karnataka HC, Telangana HC, Supreme Court

### 2. Drafting (AI-assisted, citation-grounded)
- Supported draft types: bail application (regular + anticipatory), quashing petition (BNSS s.528 / Article 226), civil review application, arbitration submission (s.34 / s.11), reply to notice, and more rolling in
- ABSOLUTE RULES enforced in every generation: no invented facts, no invented authorities, BNS vs BNSS disambiguation, placeholder-markers for missing matter data
- Multi-query retrieval for bail matters (triple-test, parity, custody-duration queries)
- Post-generation validators: statute-confusion check, UUID-leakage check, citation-coverage check, findings surfaced on the draft
- Draft lifecycle: create → generate → submit → request changes → approve → finalize (DOCX export gated on partner approval)

### 3. Research
- 14K+ indexed SC + HC judgments as of April 2026, scaling to 500K+ through 2026
- Voyage voyage-4-large embeddings (1024 dims, 32K context, legal-tuned)
- pgvector HNSW for sub-second retrieval at 10M-chunk scale
- Layer-2 structured extraction: per-chunk role (facts / arguments / reasoning / ratio / obiter / directions / procedural / metadata), doc-level judges, parties, advocates, sections cited, outcome
- Cross-encoder reranker (fastembed + Jina reranker v1 tiny)
- Per-tenant authority annotations (private notes, flags, tags) layered over the shared corpus

### 4. Hearing prep
- Pack generation tied to a specific hearing date + matter
- Seven item types: chronology, last-order summary, pending-compliance, issues likely to be framed, anticipated opposition, authority cards, oral-submission notes
- Every authority card carries a source_ref — provenance is non-negotiable

### 5. Recommendations
- Four types: forum (which court to file in), authority (best precedent), remedy, next-best-action
- All options include rationale, confidence, assumptions, missing facts
- Partner review required by default

### 6. Outside counsel
- Panel profiles with jurisdictions, practice areas, panel status
- Assignments and spend logging per matter
- Ranked recommendations: jurisdiction match + practice-area fit + prior spend + panel priority

### 7. Contracts
- Clause + obligation extraction (LLM-assisted, citation to document lines)
- Playbook comparison (rule match + deviation flagging)
- DOCX redline diff extraction (insertion / deletion / formatting with author + timestamp)

### 8. Billing
- Invoices (draft → issued → paid → void) with matter-scoped line items
- Time entries linked to invoices
- Pine Labs payment-link generation with sync-back

### 9. Governance
- Audit events on every material mutation (matter, draft, hearing pack, intake, approval, external share)
- Async audit export (JSONL + CSV)
- Ethical walls + matter ACL enforced at the API layer, not UI only
- Tenant isolation verified by continuous tests

## What CaseOps is NOT

- Not a generic AI wrapper. Every answer is grounded in a retrieved Indian authority or flagged as assumption.
- Not a replacement for a lawyer. Substantive outputs require partner review; the workflow is built around that.
- Not a training set. Customer matter data is never used for cross-tenant training.
- Not a black-box judge-scoring tool. The product does not rank judges on favorability — PRD §10.6 is explicit on that.

## Current deployment

- Region: Mumbai (asia-south1) on Google Cloud
- API: Cloud Run with Cloud SQL Postgres 17 + pgvector
- Web: Cloud Run Next.js 16 App Router
- SSL: Google-managed via global HTTPS load balancer

## Contact

- Demo requests: ${siteConfig.url}
- Direct: ${siteConfig.contact.email}
- Documentation (coming): ${siteConfig.url}/docs
`;

export function GET() {
  return new NextResponse(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=3600",
    },
  });
}
