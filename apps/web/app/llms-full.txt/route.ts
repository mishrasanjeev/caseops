import { NextResponse } from "next/server";

import { siteConfig } from "@/lib/site";

// /llms-full.txt is the full-content companion to /llms.txt. It is
// public marketing and guide content only; authenticated /app/* data is
// disallowed in robots.txt and never appears here.

const body = `# CaseOps - Indian Legal Operating System

${siteConfig.description}

Practical public evaluation checklist: ${siteConfig.url}/resources/legal-matter-management-india

## Ownership

- Product owner: ${siteConfig.ownership.legalOwner}
- Inventor/Owner: ${siteConfig.ownership.inventorOwner}
- Owner contact: ${siteConfig.ownership.emails.join(", ")}

## What CaseOps is

CaseOps is a matter-native legal operating system built for Indian legal practice, not a generic workflow tool or a retrofitted US-first product. The system is organized around matters, tenants, source-backed legal work, and auditable review.

It supports Indian litigation and legal-operations workflows: BNS, BNSS, BSA, CrPC, CPC, Arbitration Act, Companies Act and other Indian sources; Supreme Court, High Courts, lower courts, tribunals and forums where lawful source access and source-quality proof exist; and Indian billing fields for law-firm invoices.

## Product status labels

Every public claim is classified as one of: live, review-first, provider-gated, founder-only, disabled until UAT, or planned. Pine Labs production payments are disabled until UAT evidence and founder go/no-go are complete. OIDC/SAML SSO, SCIM, private enterprise deployment, and autonomous scoped-agent execution are planned/readiness-only. Google Workspace, Microsoft 365, inbound email, SMS, WhatsApp, and court-provider automation are provider-gated where credentials, admin consent, webhook signing, or legal source proof is missing.

## Who it is for

- **Indian law firms**: solo to mid-size litigation teams that need matter management, tracked case updates, court-order compliance review, drafting, hearing prep, cause lists, and matter billing.
- **Corporate legal / General Counsel teams**: intake, contracts, obligation tracking, outside-counsel spend, panel management, and auditable matter review.
- **Litigation partners**: source-backed AI assistance with lawyer review and no outcome predictions; generated text can still contain errors, so cited authorities and facts must be verified.
- **IP practitioners**: trade mark and patent docketing, renewals, journal watch, Madrid, recordals and client reporting, with registry data entered or imported by the team.

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

- Scheduled production refresh covers explicitly bookmarked cases and bounded batches of active matters with a reliable CNR or case-number-plus-court identity
- Closed, Disposed, ambiguous, mismatched, and unsupported matters are not updated
- Default settings: CASEOPS_CASE_TRACKING_DAILY_WINDOW_START=18:00, CASEOPS_CASE_TRACKING_DAILY_WINDOW_END=20:00, CASEOPS_CASE_TRACKING_DAILY_TIMEZONE=Asia/Kolkata
- The scheduled job starts at 6 PM IST inside the 6 PM-8 PM execution window
- No new provider calls start after 8 PM IST unless an operator uses an explicit force/local override
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
- Generation is instructed not to invent facts or authorities, checks BNS/BNSS attribution, and marks gaps with placeholders such as "[citation needed]"; these checks do not catch every error, so verify each authority and fact
- Drafts carry inline citations, grounding panels, reviewer findings, version history, and approval audit
- Research uses indexed shared public Indian authorities, structured extraction, reranking, tenant-private workspace notebook saves, and explicit no-result behavior when grounding is insufficient

### 7. Hearing prep and litigation intelligence

- Hearing packs include chronology, last-order summary, pending compliance, likely issues, opposition points, authority cards, and oral-submission notes
- Litigation Intelligence reviews proceeding signals, affidavit gaps, mock-hearing feedback, bench context, source readiness, knowledge-graph links, and transcript-first coaching with source links and confidence
- Decision-support surfaces do not provide legal advice, outcome forecasts, judge scoring, biometric analysis, or unsupported court-strategy claims

### 7C. Canonical judge research

- Judge profiles use canonical judge-decision mappings, not free-text name coincidence
- Mapped judgments expose court, citation, date, source action, mapping confidence, retained evidence, bounded filters, and cursor pagination
- Coverage states distinguish no mapped court corpus, no mapped judgments for the selected judge, and no filter matches
- Low-confidence mappings remain visible for review but are excluded from descriptive analytics
- Staff curators can resolve individual collision evidence slots, add sourced judge and bench aliases, merge duplicate identities with optimistic concurrency, and reprocess authority mappings; writes are capability-gated and audited
- The automated judge-mapping refresh is deployed but remains paused until source, provider, legal, and UAT approval
- Judge profiles do not provide personality, bias, emotion, lawyer-favoritism, success-probability, or outcome-forecast claims

### 7A. Trademark opposition docketing

- Application and opposition identifiers remain separate, including explicit pending Registry allocation
- Applicant work covers governed counterstatement and Rule 46 decisions; opponent work covers governed notice filing/correction, separate service, Rule 45 and Rule 47 decisions
- Critical opposition deadlines require distinct primary and backup owners, while rejected filings and missing client instruction create shared corrective or escalation work without falsely advancing the legal stage
- Shared work records complete Rules 45-47 affidavit packages and further evidence only after matching leave or order; it extends a confirmed legal deadline by superseding rather than overwriting it
- Hearing preparation and post-hearing notes link the canonical shared hearing, while an opposition order records affected records, costs, compliance directions, appeal review, and the final document
- An appeal link preserves the original opposition order and points to a separate appeal proceeding plus appeal identifier, or to an accessible Matter
- Withdrawal and settlement closure use the evidence-backed opposition stage history; translation, security-for-costs, multi-class partial outcomes, and downstream disposition remain separate later slices

### 7B. IP and Matter relationships

- One IP docket can have effective-dated operational, litigation, advisory, appeal, enforcement, billing, and other relationships to accessible Matters
- Creating an IP docket with a Matter creates the operational relationship; additional roles are references and do not become lifecycle parents
- Matter and IP lifecycle states remain independent and display side by side; disposing or reopening one record does not mutate the other
- Accessible IP legal events compose into a linked Matter timeline by source reference, without a duplicate Matter activity record
- Relationship retirement preserves history; retiring the operational role clears only the compatibility Matter pointer
- Access-policy mismatches are visible to authorized users, while readers who cannot access both records receive no relationship rows, counts, or hidden identifiers

### 8. Contracts and outside counsel

- Contracts support clause extraction, playbook comparison (matched, deviation or missing), obligation tracking, and a redline viewer
- The redline viewer reads Word's own tracked changes in one .docx: insertions, deletions, moved passages (counted once, not as a deletion plus an insertion) and formatting changes, with author, time and paragraph
- When the file holds tracked changes it cannot display (images, table structure, numbering, headers, footers, notes or comments) an amber warning says so; "Clean document" appears only when there are no shown and no hidden changes
- The viewer does not compare two separate files, accept or reject changes, or export a newly tracked Word document
- Outside counsel supports panel profiles, contacts, jurisdiction/practice-area coverage, matter assignments, fee/budget fields, spend logging, and payment state where supported; it does not promise generated brief packets, alert enforcement, outcome history, realization, or aging rollups

### 8A. IP workspace

- Availability: not part of the self-serve plans; CaseOps adds it to a workspace's plan on request and a workspace admin completes setup
- Registry data is entered or imported by the team; there is no live IP India or WIPO feed, and curated IP India source links are references, not live records
- Trade mark docket and portfolio: one-at-a-time creation or CSV/XLSX import with validation and duplicate decisions; list, grid, family and deadline-tracker views with saved views
- Deadline control: team workload, escalations, acknowledgement, calendar-copy drift checks and signed control reviews
- Renewals: client instruction notifications, recorded instructions (renew, do not renew, defer, clarification required) with authority and evidence, and evidence-backed filing, registry acceptance and certificate transitions
- Journal watch: watch profiles; manual journal intake records each entry to compare; hit review with dispositions and handoff into opposition, enforcement, task, deadline or client report work
- Madrid international registrations and designations with WIPO evidence the team records; post-registration recordals from draft to registry acceptance; foreign-associate instructions
- Controlled IP documents: previewed controlled names, confidentiality and privilege labels, review/approval/filing states and versions beside the original; retirement keeps the file, versions and audit trail, lists every record still relying on the document first, cannot be undone, and is blocked for a document already published to a client
- Reports: portfolio, status, opposition, deadline, renewal, watch and workload reports; selected reports can be published to a client through the IP client portal
- Patent and specialist IP (designs, copyright, domain names, GI, plant varieties) cover intake and record-keeping

### 8B. Teams and matter visibility

- Admins create teams, departments or practice areas and mark team leads
- Team-scoped matter visibility, when switched on, limits non-owners to their teams' matters plus firm-wide matters with no team; owners always see every matter
- The team-lead flag is recorded, audited and carried over during offboarding; it does not yet grant extra permissions
- Restricted matters and ethical walls are enforced by the server on every list, search and detail view; a walled person gets "not found" and the attempt is audited

### 8C. Workspace assistant

- Answers factual questions about the matters, IP records and documents the user is permitted to see, within an explicit scope, and cites the exact record behind each answer
- Opening a citation rechecks access and source version and is recorded in the audit log; if either changed, the user is asked to ask again
- Questions about statutes, judgments, precedent or legality are refused and routed to Research; if no permitted record supports an answer, it says so
- Proposed drafts, tasks and field changes are written only after the user confirms a reviewed preview
- Off until a workspace owner enables it under the workspace AI policy; not legal advice

### 8D. Client and outside-counsel portals

- Clients and outside counsel sign in separately from the firm's workspace with an emailed link valid for 30 minutes; email delivery must be configured
- Clients see only matters shared with them (Overview, Comms, Hearings, KYC) and IP records with approved publications; they can reply, submit KYC and send instructions for the firm's acknowledgement
- Outside counsel see only assigned matters and can upload work product, submit invoices and log time; files are scanned before they appear to the firm

### 8E. Court sync and the mobile app

- Court sync covers the Supreme Court of India and the Delhi, Bombay, Karnataka, Madras and Telangana High Courts; suggested next-hearing dates arrive with their source for a lawyer to accept or reject
- Other courts use eCourts case tracking through a paid court-data provider within the workspace budget, or hearings entered by hand
- The native iOS and Android app is a development candidate and is not yet in the App Store or Google Play; the web app works in phone and tablet browsers

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
- No live IP India or WIPO connection; IP registry evidence and journal entries are recorded by the team
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
- For law firms: ${siteConfig.url}/law-firms
- For general counsels: ${siteConfig.url}/general-counsels
- For solo lawyers: ${siteConfig.url}/solo-lawyers
- Pricing: ${siteConfig.url}/pricing
- Sign in: ${siteConfig.url}/sign-in
- Forgot password: ${siteConfig.url}/account/forgot-password

## Contact

- Demo requests: ${siteConfig.url}
- Direct: ${siteConfig.ownership.emails[0]}
`;

export function GET() {
  return new NextResponse(body, {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=3600",
    },
  });
}
