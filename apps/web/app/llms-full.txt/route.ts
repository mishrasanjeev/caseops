import { NextResponse } from "next/server";

import { siteConfig } from "@/lib/site";

// /llms-full.txt is the full-content companion to /llms.txt. It is
// public marketing and guide content only; authenticated /app/* data is
// disallowed in robots.txt and never appears here.

const body = `# CaseOps - Indian Legal Operating System

${siteConfig.description}

## What CaseOps is

CaseOps is a matter-native legal operating system built for Indian legal practice, not a generic workflow tool or a retrofitted US-first product. The system is organized around matters, tenants, source-backed legal work, and auditable review.

It supports Indian litigation and legal-operations workflows: BNS, BNSS, BSA, CrPC, CPC, Arbitration Act, Companies Act and other Indian sources; Supreme Court, High Courts, lower courts, tribunals and forums where lawful source access and source-quality proof exist; and Indian billing fields for law-firm invoices.

## Product status labels

Every public claim is classified as one of: live, review-first, provider-gated, founder-only, disabled until UAT, or planned. Pine Labs production payments are disabled until UAT evidence and founder go/no-go are complete. OIDC/SAML SSO, SCIM, private enterprise deployment, and autonomous scoped-agent execution are planned/readiness-only. Google Workspace, Microsoft 365, inbound email, SMS, WhatsApp, and court-provider automation are provider-gated where credentials, admin consent, webhook signing, or legal source proof is missing.

## Who it is for

- **Indian law firms**: solo to mid-size litigation teams that need matter management, tracked case updates, court-order compliance review, drafting, hearing prep, cause lists, and matter billing.
- **Corporate legal / General Counsel teams**: intake, contracts, obligation tracking, outside-counsel spend, panel management, and auditable matter review.
- **Litigation partners**: source-backed AI assistance with lawyer review, no invented facts, no invented authorities, and no unsupported outcome claims.

## Core workflows

### 1. Matter management

- Intake queue to matter creation
- Matter cockpit with Overview, Timeline, Tasks & Deadlines, Documents, Notices, Drafts, Hearings, AI Recommendations, Strategy Plan, Predictive Intelligence, Intelligence Review, Knowledge Graph, Statutes, Communications, Billing, and Matter Audit
- Lifecycle terminology uses **Dispose** in the UI and **disposed** in API responses for completed matters
- Legacy **closed** input is normalized to **disposed** during the compatibility window
- Server-side roles, capabilities, and matter access restrictions enforce tenant-private access on route/query/write boundaries
- Next-hearing provenance records source, source reference, actor, old date, new date, reason, timestamp, manual lock, and conflict suggestions

### 1a. Sign-in and password reset

- /sign-in includes a visible "Forgot password?" link that preserves typed workspace slug and email in encoded query parameters
- /account/forgot-password accepts company slug and work email, validates them client-side, and always shows generic anti-enumeration success copy
- /api/auth/password-reset/start is public, rate-limited, and returns the same public shape for known and unknown accounts in production-like environments
- Reset links point to /account/reset-password?token=..., are single-use, expire after 60 minutes, and never contain or email a raw password
- Reset completion stores the new session through the existing auth response/cookie path and revokes older sessions for that membership
- Local/test debug tokens are for automated verification only and are not rendered in browser UI

### 1b. Intake and optional conflict review

- Intake requests move through triage and can be promoted into matters when scope is clear
- Conflict checks compare the proposed opposing and related parties against workspace clients and matters
- Candidate similarity is a review aid, not automatic clearance
- A partner or admin records cleared, conflicted, or an explicit waiver with a note
- Conflict checks are optional review evidence, not a status gate; direct New Matter creation starts Active by default, and a matter kept in Intake or On hold can move to Active with no check or with any check result
- A check from before a material party-scope change or matter reopen remains historical; run a fresh check before describing the matter as currently cleared, but never block activation on it

### 1c. Notices and reply deadlines

- Central route: /app/notices; legacy matter workflow: /app/matters/{matter_id}/notices
- Central records can be standalone or linked to zero, one, or multiple accessible matters and may have an optional owner and primary file
- Received and sent tabs, summary counters, search, status, matter, owner, and reply-due filters cover the tenant-safe global register
- Received notices can track reply-required state and reply due date; editable central records support status and owner updates
- Legacy matter attachment notices are visible and downloadable in the central register but explicitly read-only there
- Sent notices do not create reply deadlines

### 2. Tracked case refresh

- Scheduled production refresh is opt-in by default: only explicitly tracked/bookmarked cases are refreshed
- Eligible matters with CNR or case numbers are not automatically refreshed unless a tenant admin enables auto-tracking later
- Default settings: CASEOPS_CASE_TRACKING_DAILY_WINDOW_START=16:00, CASEOPS_CASE_TRACKING_DAILY_WINDOW_END=18:00, CASEOPS_CASE_TRACKING_DAILY_TIMEZONE=Asia/Kolkata
- The scheduled job should start in the 4 PM-6 PM IST window, preferably around 4:30 PM IST
- No new provider calls start after 6 PM IST unless an operator uses an explicit force/local override
- Unfinished backlog persists and resumes on the next run
- Per-tenant batching prevents one tenant consuming the whole window
- Disabled or misconfigured providers make no external calls and record safe skipped/blocked state
- Provider operations surfaces attempted, refreshed, changed, skipped, blocked, provider-call, error, run-window, started, ended, partial, and backlog metrics

### 3. Court-order compliance extraction

- Supported sources: auto-fetched lawful adapter orders, manually created court orders, and uploaded order documents
- Manual uploads accept PDFs, DOC/DOCX, and images only after file-safety checks and text/OCR availability
- OCR and extraction have pending, failed, retry, and redacted-error states
- Deterministic proceeding extraction runs first
- AI extraction runs only when tenant AI policy allows it
- AI outputs must pass JSON schema validation and dedupe
- Compliance items are review-required by default and include description, responsible party, due_on, timeline text, filing requirement, court direction, next action, source order/attachment, source snippet/page/paragraph, confidence label, status, review status, generated task/deadline ids, and dedupe key
- Generated tasks/deadlines stay draft or review-linked unless a tenant/admin setting enables auto-activation
- Lawyers can confirm, edit, reject, waive, complete, or retry items
- Rejected items do not appear as active compliance
- Every AI run creates model-run and audit metadata without exposing raw prompts, raw LLM responses, provider tokens, raw provider payloads, internal costs, or tenant-private data to unauthorized users

### 4. Deadline and hearing caution

- Deadline calculations default to calendar-day convention shown to the user
- Court holidays are not assumed unless a court calendar exists
- Ambiguous phrases such as "from today", "within two weeks", "next date", or missing order dates remain review-required
- Every computed date shows source snippet and confidence
- CaseOps never invents due dates
- Manual next-hearing lock prevents overwrite unless a user accepts a suggestion
- High-confidence future provider dates may update only when there is no conflict
- Past dates do not replace future dates unless final/disposed status is explicit

### 5. Cause-list generation

- Route: /app/cause-list
- API: /api/cause-lists preview and PDF download
- Filters: date or date range, court, practice area, matter status, include/exclude disposed matters, source, and sort
- Required output: serial number, file number, court name, case number, case title, judge name, court number, item number, lawyers appearing, hearing date, and missing-field warnings
- Missing values display "Not available" or a professional warning in preview
- Incomplete rows are corrected in the underlying matter, hearing, or imported cause-list record; the page does not expose a per-row override editor
- PDF is A4 portrait, black-and-white printable, with firm header/logo where configured, generated timestamp, filters, repeated table header, pagination, and page number footer
- Downloads are audited with filters, row count, actor, timestamp, checksum, and file name

### 6. Drafting and research

- Drafting supports bail applications, quashing petitions, civil reviews, arbitration submissions, replies, and escalation drafts
- Generation rules: no invented facts, no invented authorities, BNS/BNSS disambiguation, and placeholders for missing matter data
- Drafts carry inline citations, grounding panels, reviewer findings, version history, and approval audit
- Research uses indexed shared public Indian authorities, structured extraction, reranking, tenant-private workspace notebook saves, and explicit no-result behavior when grounding is insufficient

### 7. Hearing prep and litigation intelligence

- Hearing packs include chronology, last-order summary, pending compliance, likely issues, opposition points, authority cards, and oral-submission notes
- Litigation Intelligence reviews proceeding signals, affidavit gaps, mock-hearing feedback, bench context, source readiness, knowledge-graph links, and transcript-first coaching with source links and confidence
- Decision-support surfaces do not provide legal advice, outcome forecasts, judge scoring, biometric analysis, or unsupported court-strategy claims

### 7A. Trademark opposition docketing

- Application and opposition identifiers remain separate, including explicit pending Registry allocation
- Applicant work covers governed counterstatement and Rule 46 decisions; opponent work covers governed notice filing/correction, separate service, Rule 45 and Rule 47 decisions
- Critical opposition deadlines require distinct primary and backup owners, while rejected filings and missing client instruction create shared corrective or escalation work without falsely advancing the legal stage
- Hearing, order, appeal, settlement, translation, security-for-costs, and downstream disposition remain separate later-stage workflows

### 8. Contracts and outside counsel

- Contracts support clause extraction, playbook comparison, obligation tracking, and parsing/viewing DOCX tracked changes; the current UI does not export a tracked Word redline or claim version lineage
- Outside counsel supports panel profiles, contacts, jurisdiction/practice-area coverage, matter assignments, fee/budget fields, spend logging, and payment state where supported; it does not promise generated brief packets, alert enforcement, outcome history, realization, or aging rollups

### 9. Matter billing and invoice PDFs

- Matter billing is separate from CaseOps SaaS subscription billing
- Tenant admins configure billing profiles at /app/admin/matter-billing
- Profiles include legal name, address, GSTIN, PAN, invoice prefix/sequence, currency, payment terms, SAC/HSN or service classification, footer/note, and branding/header where supported
- Client billing fields include billing name, address, and GSTIN where available
- Rate resolution supports user, role, practice-area, and default hourly rates
- Fixed-fee arrangements, milestones, retainers/advances, expense/reimbursement categories, payment adjustments, and manual line items are supported where applicable
- Tax is calculated server-side from stored invoice data, including place of supply, taxable value, CGST/SGST/IGST split, totals, grand total, amount paid, outstanding amount, and TDS deduction/payment adjustment fields where recorded
- Double billing prevention blocks already-invoiced time entries from being billed again
- Downloadable invoice PDFs render from server-side invoice data
- Billing profile/rate changes and invoice downloads are audited
- External payment links are used only when a tenant explicitly configures an approved provider

## Safety and governance

- No captcha/session-gated court-source bypass
- No unapproved external provider calls
- No live court/provider calls unless configured safe mode or approved provider configuration exists
- No Pine Labs production payment activation until UAT evidence and founder go/no-go are complete
- No autonomous scoped-agent tool execution; agent grants, execution audit, and revocation are readiness scaffolding until activated
- No external email/SMS/WhatsApp notifications unless provider delivery is explicitly configured, template/DLT approvals are complete where applicable, and UAT evidence is recorded
- Durable in-app notification intents are the safe default
- Strict tenant isolation applies to tenant-private routes, queries, writes, documents, and embeddings; shared public authority records remain separate from tenant-owned data
- Auditability is preserved for user, admin, and system actions
- Raw provider payloads, raw prompts, raw LLM responses, provider tokens, internal costs, and unauthorized tenant-private data are not exposed to tenant-facing users
- Customer matter data is not used for cross-tenant training by default

## Current deployment

- Region: Mumbai (asia-south1) on Google Cloud
- API: Cloud Run with Cloud SQL Postgres and pgvector
- Web: Cloud Run Next.js App Router
- SSL: Google-managed via global HTTPS load balancer

## Canonical public pages

- Home: ${siteConfig.url}
- User guide: ${siteConfig.url}/guide
- Sign in: ${siteConfig.url}/sign-in
- Forgot password: ${siteConfig.url}/account/forgot-password

## Contact

- Demo requests: ${siteConfig.url}
- Direct: ${siteConfig.contact.email}
`;

export function GET() {
  return new NextResponse(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=3600",
    },
  });
}
