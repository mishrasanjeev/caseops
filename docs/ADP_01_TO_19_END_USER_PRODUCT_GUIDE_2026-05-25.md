# CaseOps ADP-01 to ADP-19 End User Product Guide

Last updated: 2026-05-25

This guide explains the product capabilities delivered through ADP-19 and how
law firm and legal operations users can use them in CaseOps. It is written for
end users and administrators, not developers.

## General Safety Notes

- CaseOps helps organize legal work, documents, research, drafting, and
  operational workflows. It does not replace professional legal judgment.
- AI-assisted outputs should be reviewed by a qualified lawyer before use.
- Features that show summaries, recommendations, alerts, or extracted fields are
  review aids. They are not legal advice, outcome predictions, success
  probabilities, or judge/court recommendations.
- Calendar, judgment, law update, and email-invitation features are in-app and
  review-driven unless the product explicitly says otherwise.
- Do not upload or enter secrets, passwords, private keys, or provider tokens in
  ordinary matter notes, documents, comments, or descriptions.

## ADP-01: Storage Governance

Purpose: Track storage use and enforce safer upload behavior.

How to use:

1. Upload matter documents through the normal matter document flow.
2. Review storage or quota messages shown by the app before retrying failed
   uploads.
3. Ask an administrator to review firm-level storage settings if uploads are
   blocked by quota.

What to expect:

- The system tracks storage at the firm level.
- Uploads may be blocked when governance limits are exceeded.
- Storage governance does not expose storage keys or internal object paths to
  end users.

## ADP-02: AI Token Governance

Purpose: Keep AI usage controlled by firm and user quotas.

How to use:

1. Use AI features normally, such as Matter File Q&A, recommendations, and
   drafting assistance.
2. If an AI request is blocked, review the quota or policy message.
3. Ask an administrator to adjust approved AI budgets or policies if needed.

What to expect:

- AI requests are checked against policy and quota controls.
- Over-limit requests fail closed before provider calls.
- Audit metadata avoids storing raw prompts and answers.

## ADP-03: Objective-Based Recommendations

Purpose: Generate matter recommendations tied to an explicit objective.

How to use:

1. Open a matter and go to the recommendations area.
2. Choose or enter a clear objective, such as preparing for hearing, improving
   evidence organization, or reviewing next procedural steps.
3. Review recommendations with their supporting context.
4. Accept only the actions that fit your professional judgment.

What to expect:

- Recommendations are framed around your selected objective.
- The system should avoid unsupported legal conclusions and outcome prediction.
- Recommendations remain advisory workflow suggestions, not legal advice.

## ADP-04: Contextual Legal Research

Purpose: Search legal context using existing source-backed authority data.

How to use:

1. Open the research area.
2. Enter a natural-language legal or factual issue.
3. Review returned issues, statutes, authorities, and source references.
4. Use weak-coverage messages as a warning that more research is needed.

What to expect:

- Results should include source-backed references where available.
- The feature does not run new corpus ingest or guarantee exhaustive coverage.
- Use citations and authority links as starting points for lawyer review.

## ADP-05: Unified Communication Timeline

Purpose: View matter communications in one chronological timeline.

How to use:

1. Open a matter and select the communications page.
2. Review emails, notes, and related communication entries in chronological
   order.
3. Use filters to narrow by type, direction, or source where available.
4. Treat internal-only notes as firm-side content.

What to expect:

- Timeline entries are matter-access controlled.
- Internal notes should not appear in outside-counsel or portal views unless the
  product explicitly allows them.
- Full email bodies and attachment payloads are not exposed through the timeline
  surface.

## ADP-06: Court and Judge Context Explorer

Purpose: Explore descriptive court and judge context from existing records.

How to use:

1. Open the courts or judge profile pages.
2. Review practice-area counts, court-wise counts, statute or act trends, and
   source-backed case lists where available.
3. Pay attention to sample-size and coverage limitations.

What to expect:

- Analytics are descriptive and historical.
- Low sample sizes suppress pattern claims and show limitations.
- The feature does not recommend the best judge, best bench, best court, most
  suitable judge, or probability of success.

## ADP-07: Calendar Sync Status and Conflict Review

Purpose: Show calendar sync readiness and surface reviewable conflicts.

How to use:

1. Open the calendar page.
2. Review the sync status panel.
3. Connect Outlook only through the approved calendar connection flow.
4. Use manual visible-range sync where available.
5. Review conflict candidates before taking further action.

What to expect:

- Current Outlook sync is bounded and manual.
- Durable always-on sync remains pending until the required automation
  prerequisites are complete.
- Reminder or notification delivery is not active unless the product explicitly
  says it is.

## ADP-08: Multilingual Matter File Q&A

Purpose: Ask questions about uploaded matter documents and optionally receive a
local-language aid.

How to use:

1. Open a matter's documents page.
2. Use Matter File Q&A to ask a question grounded in uploaded matter documents.
3. Keep English selected for the default response, or choose a supported local
   language when available.
4. Review the English answer as authoritative.
5. Treat local-language output as a translation aid, not a separate legal
   analysis.

Supported foundation languages:

- English (`en`)
- Hindi (`hi`)
- Marathi (`mr`)
- Gujarati (`gu`)
- Tamil (`ta`)
- Telugu (`te`)
- Kannada (`kn`)
- Bengali (`bn`)

What to expect:

- Answers remain grounded only in uploaded matter documents.
- Source cards and snippets remain tied to original uploaded evidence.
- Unsupported languages fail closed.
- Refusals for missing, processing, or insufficient evidence remain refusals.

## ADP-09: Outside Counsel Spend Tracking

Purpose: Track matter-level outside counsel spend and payment status.

How to use:

1. Open a matter's outside counsel page.
2. Review assigned counsel, agreed fee, amount paid, amount pending, invoice
   references, and payment status.
3. Update factual spend or payment tracking fields if you have permission.
4. Use the spend summary to understand operational status.

What to expect:

- Pending amount is computed from recorded agreed and paid amounts.
- Multi-currency values should be reviewed carefully and not treated as one
  combined currency unless the UI says so.
- The feature does not process payments or score outside counsel performance.
- Outside counsel portal users should not see firm-internal spend fields unless
  explicitly configured and tested.

## ADP-10: Client Verification Workflow

Purpose: Track client or matter verification status through review states.

How to use:

1. Open the client page.
2. Review verification status and required document metadata.
3. Mark verification requested, submitted, under review, verified, rejected, or
   expired according to the matter's process.
4. Record bounded rejection or rework reasons where allowed.

Supported statuses:

- not required
- required
- requested
- submitted
- under review
- verified
- rejected
- expired

What to expect:

- Verification uses existing KYC/client metadata foundations.
- Document references are references only; the workflow does not expose identity
  document payloads or storage keys.
- There is no biometric verification or automated identity scoring.

## ADP-11: Bulk Matter Upload Dry Run

Purpose: Validate a bulk matter import before creating any matters.

How to use:

1. Prepare a supported mapping file or manifest.
2. Run the bulk matter import dry run.
3. Review valid rows, invalid rows, duplicate candidates, missing fields, and
   unsupported document references.
4. Correct the source file and rerun the dry run until the plan is clean.

What to expect:

- Dry run does not create matter rows.
- Dry run does not create attachment rows.
- Dry run does not store uploaded file payloads.
- ZIP or folder handling, where shown, is metadata-only and does not run OCR,
  document processing, corpus ingest, or embeddings.

## ADP-12: Google Drive Bounded Manual Import

Purpose: Plan a bounded Google Drive import without autonomous sync.

How to use:

1. Open the Google Drive import area where available.
2. Review provider configuration status.
3. Validate folder or file metadata for a matter.
4. Review the import plan before any later approved execution workflow.

What to expect:

- The foundation validates metadata and fails closed when config is missing.
- It does not contact Google APIs for autonomous sync unless a later approved
  feature explicitly provides that.
- It does not store OAuth tokens, Drive payloads, or file contents through the
  planning surface.

## ADP-13: Party-Based Contract Clause Extraction

Purpose: Extract bounded party-specific contract clause metadata for review.

How to use:

1. Open the contract clause extraction or contract analysis area.
2. Select the contract or available contract text source.
3. Review extracted party names, clause categories, obligations, dates, and
   other bounded clause metadata.
4. Confirm or correct extracted values before relying on them.

What to expect:

- Extraction is a review aid and should not replace contract review.
- The feature avoids storing raw prompt or answer payloads in audit metadata.
- Extracted clause content should stay bounded and source-linked.

## ADP-14: Contract Playbook Admin and Compare

Purpose: Manage contract playbooks and compare clauses against approved
positions.

How to use:

1. Open the contract playbook administration area.
2. Create or update playbook positions for clause categories.
3. Compare a contract's clauses against the playbook.
4. Review deviations and required approvals.

What to expect:

- Playbooks are tenant-scoped.
- Comparison findings are workflow support, not legal advice.
- Users should review all deviations before negotiation or filing decisions.

## ADP-15: Drafting Data Extraction Review Queue

Purpose: Extract drafting facts from uploaded matter documents and route them
through lawyer review.

How to use:

1. Open a matter's drafting page.
2. Run the drafting data extraction review queue where available.
3. Review suggested fields such as FIR number, case number, police station,
   party names, dates, and statute sections.
4. Confirm, override, or reject each field.
5. Generate drafts knowing only confirmed or overridden reviewed fields feed the
   reviewed-facts block.

What to expect:

- Pending or rejected suggestions do not feed draft generation.
- Explicit stepper facts remain authoritative.
- Source snippets are bounded and should match existing extracted document text.
- No raw document text, OCR text, prompt, answer, or storage key is shown in the
  review queue.

## ADP-16: Court-Specific Draft Format Profiles

Purpose: Surface court-specific drafting format profiles and required-field
warnings.

How to use:

1. Open a draft detail or export view.
2. Choose or review the selected court profile.
3. Review required-field warnings before export or filing preparation.
4. Use warnings as a checklist; do not let the system fabricate missing values.

Profile categories:

- District Court
- High Court
- Supreme Court
- Tribunal
- Generic

What to expect:

- Profile rules affect export/checklist metadata where supported.
- Missing required fields are warnings or review findings, not legal sufficiency
  conclusions.
- Normal draft creation remains available.

## ADP-17: Judgment Monitoring In-App Alert Center

Purpose: Create saved in-app judgment alert rules against existing authority
records.

How to use:

1. Open the research or judgment alerts area.
2. Create an alert rule with bounded filters such as query terms, court, judge,
   practice area, statute terms, document type, and date range.
3. Run or preview matches manually.
4. Review in-app alerts and mark them read or dismissed.
5. Use digest preview as an in-app summary only.

What to expect:

- Alerts are generated from existing AuthorityDocument records only.
- Matching is deterministic and manual.
- No crawling, ingestion, LLM, provider call, scheduler, webhook, or external
  notification delivery is performed.
- Alert snippets are bounded and do not expose full judgment text or source
  payloads.

## ADP-18: Law Amendment and Regulatory Update Monitor

Purpose: Track legal updates and regulatory changes through in-app watchlists.

How to use:

1. Open the statutes or legal updates area.
2. Create a watchlist with at least one bounded filter, such as Act, section,
   jurisdiction, practice area, source category, update type, or date range.
3. Run or preview matches manually.
4. Review legal update records, source/provenance metadata, and relevance
   explanations.
5. Mark updates read or dismissed.

What to expect:

- Watchlists require source/provenance for every update record.
- Matching uses existing statute, statute section, authority, and source
  registry metadata.
- Digest preview is in-app only.
- The feature does not send external alerts or expose full statute, judgment, or
  regulatory text beyond existing statute detail behavior.

## ADP-19: Email Invitation to Calendar Candidate Extraction

Purpose: Extract reviewable calendar-event candidates from already imported
email or invite metadata.

How to use:

1. Open the calendar page.
2. Review the Email invitation candidates panel.
3. Scan for candidates from existing imported communications.
4. Review detected title, date/time, location, matter link, duplicate status,
   and bounded source preview.
5. Approve a candidate to create an internal CaseOps calendar item.
6. Reject candidates that should not become calendar items.

What to expect:

- Extraction is deterministic and uses existing imported communication metadata,
  subject, and bounded preview text only.
- Approval creates only an internal CaseOps calendar item.
- It does not create Outlook, Google, or other provider calendar events.
- Pending, rejected, duplicate, or skipped candidates do not create calendar
  items.
- Full email bodies, invite payloads, attachments, storage keys, and provider
  tokens are not shown through the candidate panel.

## Current Production-Use Boundaries

The following are not active as durable production automations through ADP-19:

- Durable always-on Outlook sync.
- Durable Google Drive sync.
- Durable email provider ingestion.
- Background mailbox polling.
- Provider webhooks for calendar/email ingestion.
- External notification delivery by email, SMS, WhatsApp, push, or digest.
- Legal outcome prediction or success probability.
- Judge, bench, court, or counsel scoring.

Use the delivered ADP-01 to ADP-19 features as reviewable, source-backed,
in-app workflow foundations.
