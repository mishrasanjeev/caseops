# MOD-TS modules ↔ PRD coverage + planned changes

Source: `C:\Users\mishr\Downloads\CaseOps_Session1_Missing_Modules.xlsx`
(13 modules flagged "missing" on 2026-04-20)
Audit date: 2026-04-20.

This document maps each MOD-TS module to:

1. What ships in the CaseOps repo today (file paths).
2. Which PRD section (`docs/PRD.md`) governs it.
3. Which Sprint in `docs/WORK_TO_BE_DONE.md` now owns the gap.
4. The concrete changes planned.

See `WORK_TO_BE_DONE.md` §15 for sprint-level sequencing. See the
directive in `memory/feedback_user_bias_in_recommendations.md` for the
2026-04-20 product-owner override that allows favorability analytics on
judge / court surfaces (PRD §10.6 neutrality is superseded there).

---

## Status table

| ID | Module | Shipped % | PRD § | Sprint | Top blocker |
|----|--------|---------:|-------|--------|-------------|
| MOD-TS-001 | JudgeProfile | **90 % (2026-04-20 evening)** | §10.6 | **P — DONE** | P1a/P1b/P2/P2b/P3/P4 all shipped; Layer-2 sweep running autonomously on GCE |
| MOD-TS-002 | OCR Extractor | **70 %** (Q1 DONE — `[ocr]` extras + tesseract hin/mar/tam/tel/kan in Dockerfile, commit `93b94e4`) | §9.1 / §14.4 | **Q (Q1 ✅, Q4 in progress)** | language-detect (Q2), handwritten routing (Q3), quality gate (Q4) |
| MOD-TS-003 | Legal Translator | 0 % | not covered | **U** (deferred) | Not prioritised for v1 |
| MOD-TS-004 | Case Summary | **70 %** (Q5 DONE — `services/matter_summary.py` + `GET /api/matters/{id}/summary`, commit `8d767dc`) | §9.6 / §10.3 | **Q (Q5 ✅, Q6/Q7/Q8 pending)** | regenerate button, PDF/DOCX export, timeline builder |
| MOD-TS-005 | Document Viewer | 30 % | §10.3 | **Q** | No PDF.js / annotation UI |
| MOD-TS-006 | Calendar | 40 % | §7.2 | **T** | Temporal (§5.1) + UI |
| MOD-TS-007 | Notification & Reminder | 20 % | §5.3 | **T** | Temporal (§5.1) + SMS provider |
| MOD-TS-008 | Pleading Step By Step | 30 % | §9.5 / §10.3 | **R** | Per-draft-type schema / form builder |
| MOD-TS-009 | Clients & Advocates | 50 % | §9.2 (counsel) / new | **S** | Structured `Client` entity not modeled |
| MOD-TS-010 | AutoMail Transfer | 25 % | §5.3 / §16.2 | **S/T** | Email templates + Temporal |
| MOD-TS-011 | Support (in-app) | 0 % | not covered | **W** (v2) | Out of v1 scope |
| MOD-TS-012 | Draft Generator (8 types) | 55 % | §9.5 / §10.3 | **R** | Per-type prompts / templates |
| MOD-TS-013 | Clients Verification (KYC) | 0 % | not covered | **V** (post-launch) | Regulatory / enterprise tier |

Percentage = approximate fraction of the module's scope already in
code / DB. "Shipped" means runnable in prod today; "partial" means
scaffold / data model exists but UX is missing.

---

## Per-module detail + planned changes

### MOD-TS-001 JudgeProfile — **Sprint P DONE 2026-04-20 evening**
- **Shipped**: `Judge`, `Bench`, `Court` models (`apps/api/src/caseops_api/db/models.py:2366-2451`); `/api/courts/judges/{id}` route with structured `judges_json` + practice-area histogram + decision-volume + tenure bounds + structured_match_coverage_percent (commit `73fc94a`); `/app/courts/judges/[judge_id]` page; case-to-bench matcher `GET /api/matters/{id}/bench-match` (commit `662de6a`, 16 tests green); SC sitting-judge roster enriched with DoB (16→80 %) / appointment (19→64 %) / retirement (derived, 80 %) in commit `8a88bbd`.
- **Partial**: `authority_documents.judges_json` Layer-2 coverage still climbing as GCE sweep works through buckets (per-bucket pipeline, $10 budget, 4.7 rating floor). This is the one thread that remains background work, not in-code gap.
- **PRD**: §10.6 Judge & Court Intelligence.
- **Plan status** (Sprint P, 4 phases all shipped):
  - P1a — ✅ DONE (commit `73fc94a`) — profile endpoint uses structured `judges_json` first, `bench_name` ILIKE as fallback.
  - P1b — ✅ DONE (commit `73fc94a`) — practice-area histogram, decision-volume, tenure, coverage %.
  - P2 — ✅ DONE (commit `b872f0d` + enrichment `8a88bbd`) — SC roster + DoB + appointment dates.
  - P2b — ✅ DONE (commit `8a88bbd`) — richer date extraction via per-judge profile scrape.
  - P3 — ✅ DONE (commit `662de6a`) — rule-based bench matcher; tenancy-safe route at `GET /api/matters/{id}/bench-match`.
  - P4 — ✅ DONE (earlier commit) — scoped authority retrieval in `services/authorities.search_authority_catalog`, same-forum boost. Per 2026-04-20 bias directive, boosts authorities that support the user's position. See `memory/feedback_user_bias_in_recommendations.md`.

### MOD-TS-002 OCR Extractor — **Q1 DONE, Q4 IN PROGRESS**
- **Shipped**: `services/ocr.py` with tesseract + RapidOCR backends; `should_fallback_to_ocr()` triggers on sparse pdfminer extraction; pypdfium2 page renderer; `_normalize_whitespace()` cleanup. **Q1 DONE** (commit `93b94e4`) — `[ocr]` extra installed in `apps/api/Dockerfile` along with `tesseract-ocr-{hin,mar,tam,tel,kan}` language packs.
- **Missing**: multi-language auto-detect; handwritten-specific model selection; OCR-garbage quality gate.
- **PRD**: §9.1 Document-intelligence depth, §14.4 OCR / normalisation.
- **Plan status** (Sprint Q — **Document Intelligence UX**):
  - Q1 — ✅ DONE (commit `93b94e4`) — `[ocr]` extra + tesseract language packs in prod image.
  - Q2 — pending — wire language-detect (e.g. `fasttext-lid` on first 2 kB of text) → pick tesseract `lang` pack accordingly (eng / hin / mar / tam / tel / kan).
  - Q3 — pending — handwritten pages: heuristic "stroke density > threshold" → fall through to rapidocr's handwriting model.
  - Q4 — **IN PROGRESS (Thread B, 2026-04-20 evening)** — OCR quality metric per page (confidence + length-normalised); reject pages with conf < 0.4 from chunking (prevents OCR garbage from poisoning embeddings — lever #4 in `memory/feedback_vector_embedding_pipeline.md`).

### MOD-TS-003 Legal Translator
- **Shipped**: nothing translation-related.
- **Partial**: `ocr_languages` env var is for OCR input, not translation output.
- **Missing**: the whole module.
- **PRD**: not formalised. User story exists ("bilingual research") but no PRD § covers it.
- **Plan** (Sprint U — deferred to v2):
  - U1 — decide provider: Anthropic Haiku (we already depend on it; decent Hindi / regional) vs Google Translate API vs in-house fine-tune. Default to Haiku.
  - U2 — new service `services/translation.py`. Bilingual prompt template enforcing legal-terminology preservation (BNSS vs IPC, petition / appeal, etc.).
  - U3 — `/api/matters/{id}/attachments/{id}/translate` endpoint; result stored as a sibling attachment `{original}.en.txt`.
  - U4 — UX: "Translate" action on document viewer + matter attachment card.
  - **Guardrail**: do not translate statutes / citations — they have canonical English form. Translate facts / arguments only.

### MOD-TS-004 Case Summary — **Q5 DONE, Q6/Q7/Q8 pending**
- **Shipped**: `authority_documents.summary` populated on SC / HC corpus; `HearingPack` generation includes summary; `MatterCourtOrder.summary`. **Q5 DONE** (commit `8d767dc`) — `services/matter_summary.py` + `MatterExecutiveSummary` Pydantic + `GET /api/matters/{id}/summary` endpoint (Haiku-backed, with fallback).
- **Missing**: regenerate button, PDF/DOCX export, explicit timeline derivation.
- **PRD**: §9.6 Hearing Preparation, §10.3 Drafting Studio.
- **Plan status** (Sprint Q):
  - Q5 — ✅ DONE (commit `8d767dc`) — `MatterExecutiveSummary` with overview / key_facts / timeline / legal_issues / sections_cited.
  - Q6 — pending — `POST /api/matters/{id}/summary/regenerate` route + "Regenerate summary" button on cockpit.
  - Q7 — pending — `GET /api/matters/{id}/summary.{pdf,docx}` export using existing docx template stack.
  - Q8 — pending — timeline derived from `MatterHearing` + `MatterDeadline` + `MatterCourtOrder` chronologically.

### MOD-TS-005 Document Viewer
- **Shipped**: `MatterAttachment` storage; `AuthorityAnnotation` + `AuthorityAnnotationKind` enum (flag / note / highlight); download endpoint.
- **Partial**: no PDF.js component; no in-document search UI; annotations stored but not surfaced visually.
- **Missing**: PDF viewer (web), highlight / comment UI, page navigation, zoom, batch download, in-document search.
- **PRD**: §10.3 Drafting Studio document-context.
- **Plan** (Sprint Q):
  - Q9 — install `react-pdf` (MIT) into `apps/web`. Wrap in `components/document/PDFViewer.tsx` (keyboard nav, zoom, page select, search).
  - Q10 — annotation overlay: fetch `AuthorityAnnotation` rows → draw highlights on viewer; new-highlight button POSTs to existing annotation API.
  - Q11 — attachment viewer route `/app/matters/{id}/documents/{attachment_id}/view` that renders the PDF viewer with annotation layer.
  - Q12 — full-text search inside the PDF: leverage the chunked text already in `authority_document_chunks` (for authorities) or extracted attachment text (for matter docs).

### MOD-TS-006 Calendar
- **Shipped**: `MatterHearing` (status SCHEDULED / COMPLETED / ADJOURNED); `MatterDeadline` + `Deadline` service; `MatterCauseListEntry` from court-sync.
- **Partial**: data models solid; no calendar UI.
- **Missing**: calendar week / month view, event CRUD UI, Google / Outlook sync, push / SMS reminders.
- **PRD**: §7.2 Task / Deadline / Obligation.
- **Plan** (Sprint T — **Calendar & Notifications**, depends on §5.1 Temporal):
  - T1 — web component `components/calendar/CalendarGrid.tsx` (week + month toggle). Reads hearings / deadlines / cause-list entries via a unified `/api/matters/me/calendar` endpoint.
  - T2 — event editor modal (create hearing / deadline / custom event).
  - T3 — Google Calendar push: one-way sync via `calendar.events.insert`. Per-user OAuth token stored encrypted (new `UserCalendarConnection` model).
  - T4 — Temporal workflow `schedule_reminders` that fans out T-1 day, T-1 hour, T-30 min reminders per event according to per-user rules.
  - T5 — SMS provider integration (MSG91 — India-friendly). Opt-in per user.

### MOD-TS-007 Notification & Reminder
- **Shipped**: SMTP config; `MatterDeadline` tracking.
- **Partial**: SMTP wired but no live send route.
- **Missing**: hearing-reminder service, deadline-alert delivery, SMS integration, custom / recurring reminder rules, push notifications, delivery-status tracking.
- **PRD**: §5.3 Notifications (blocked on §5.1 Temporal).
- **Plan** (Sprint T, shared with Calendar):
  - T6 — `NotificationRule` model (entity_type, trigger_offset, channel, recipient). Sensible defaults on matter creation.
  - T7 — Temporal worker picks up scheduled jobs and delivers via SMTP (SendGrid at scale) + SMS (MSG91) + web-push.
  - T8 — `NotificationEvent` audit trail with `status ∈ {queued, sent, delivered, failed}` + vendor ID for traceability.
  - T9 — in-app notification bell: poll `/api/me/notifications` (or websocket if Temporal is up).

### MOD-TS-008 Pleading Step By Step
- **Shipped**: `Draft`, `DraftVersion`, `DraftType` enum (8 types); `services/drafting.py` generates via single generic prompt.
- **Partial**: 8 draft types enumerated; single prompt works but quality varies per type.
- **Missing**: per-type form schema (case-type → fields → validations), stepwise UI, auto-suggestions (e.g. "common sections for Bail"), per-step draft preview.
- **PRD**: §9.5 Drafting Flow, §10.3 Drafting Studio.
- **Plan** (Sprint R — **Stepwise Drafting + Per-type Templates**):
  - R1 — `apps/api/src/caseops_api/schemas/drafting_templates/` with one Pydantic schema per `DraftType`. Fields: which facts are required, which statutes apply, which procedural posture to enforce.
  - R2 — per-type prompt library in `services/drafting_prompts.py`. Bail-specific prompt enforces BNSS s.483 (not BNS s.483), triple-test, custody-duration, etc.
  - R3 — `/api/drafting/templates/{draft_type}` returns the form schema; web builds a React Hook Form + Zod-validated stepper (`app/matters/{id}/drafts/new?type=bail`).
  - R4 — per-step preview: after each completed step, re-run a partial Haiku call that previews the emerging draft. Feedback-loop UX.
  - R5 — validators: re-use `services/draft_validators.py` per-type (statute confusion, UUID leakage, citation coverage).

### MOD-TS-009 Clients & Advocates Management
- **Shipped**: `Matter.client_name` (freeform); `OutsideCounsel` + `MatterOutsideCounselAssignment`; `authority_documents.advocates_json` via Layer 2.
- **Partial**: outside-counsel CRUD live; no client profile model; no comms log; no document-to-client linking.
- **Missing**: structured `Client` entity (name, phones, emails, KYC, addresses), client-profile page, communication log table, client document library.
- **PRD**: §9.2 covers counsel; clients are implicit (referenced via `Matter.client_name`) but no formal module.
- **Plan** (Sprint S — **Clients & Comms**):
  - S1 — new `Client` model: id, company_id (tenant), name, type ∈ {individual, corporate, government}, primary_contact, emails, phones, addresses, kyc_status.
  - S2 — `MatterClientAssignment` model linking matters to clients (N-N for corporate defence work).
  - S3 — `CommunicationLog` entity: direction (inbound / outbound), channel (email / call / meeting / WhatsApp), participants, summary, attachments. Manual-entry first; email-auto-capture (MOD-TS-010) later.
  - S4 — `/api/clients` CRUD + `/app/clients` + `/app/clients/{id}` pages.
  - S5 — attach communications to matters: `CommunicationLog.matter_id` nullable FK for log-only entries.

### MOD-TS-010 AutoMail Transfer
- **Shipped**: SMTP config; payment-link URLs embedded in invoices.
- **Partial**: no email-send route; no templates; no auto-share trigger.
- **Missing**: template-based emails, auto-document-sharing workflow, notification emails, delivery-status tracking, inbound-email ingestion.
- **PRD**: §5.3 Notifications, §16.2 Connectors (email / calendar).
- **Plan** (Sprint S, shared with Clients):
  - S6 — `EmailTemplate` model + seeded templates: `matter_update`, `hearing_reminder`, `document_share`, `invite_outside_counsel`, `client_onboarding`.
  - S7 — email-send service (`services/email_outbound.py`). Production uses SendGrid; dev uses SMTP.
  - S8 — "Send via email" action on document viewer → pick template → pick recipient(s) from `CommunicationLog` / `Client` / `OutsideCounsel` → queue via Temporal → persist to `CommunicationLog`.
  - S9 — delivery tracking: SendGrid webhook → `CommunicationLog.delivery_status`.
  - S10 — inbound: per-tenant `{slug}@inbound.caseops.ai` address; SES / Postmark webhook parses and attaches to matter by `matter_id` in subject tag.

### MOD-TS-011 Support
- **Shipped**: marketing FAQ component only; nothing in-app.
- **Missing**: in-app FAQ, live chat, ticket system, feedback form, help docs.
- **PRD**: out of v1 scope.
- **Plan** (Sprint W — **Support**, scheduled v2):
  - W1 — Intercom-style embed on authenticated shell. SaaS: Crisp (free tier) or Plain.com.
  - W2 — in-app feedback: "Send feedback" button → posts to a GitHub issue via a bot account.
  - W3 — `/help` route with markdown-rendered docs from `docs/user_guides/`.
  - W4 — defer: dedicated ticket system until > 10 paying tenants.

### MOD-TS-012 Draft Generator (8 types)
- **Shipped**: `DraftType` enum — Bail, Anticipatory Bail, Divorce Petition, Property Dispute Notice, Cheque Bounce Notice, Affidavit, Criminal Complaint, Civil Suit. Generic LLM prompt used for all.
- **Partial**: all 8 types generate end-to-end but with variable quality.
- **Missing**: per-type templates, per-type prompts, per-type auto-suggestions, per-type quality benchmarks.
- **PRD**: §9.5, §10.3.
- **Plan** (Sprint R — same sprint as stepwise drafting; tightly coupled):
  - R6 — `services/drafting_prompts.py` — one specialised system prompt per `DraftType`, enforcing domain statutes + procedural posture. Builds on the ABSOLUTE-RULES prompt from Phase 19.
  - R7 — per-type seed cases in `tests/fixtures/drafting/{type}.json` — 3 canonical matter fixtures per type → golden draft for regression testing.
  - R8 — `caseops-eval-drafting --type bail` runs the suite, measures citation-coverage + statute-correctness (BNSS vs BNS, etc.).
  - R9 — per-type auto-suggest on form: e.g. `Bail → suggest standard BNSS sections`, `Cheque Bounce → suggest s.138 NI Act boilerplate`.

### MOD-TS-013 Clients Verification (KYC)
- **Missing**: entire module.
- **PRD**: not in scope.
- **Plan** (Sprint V — **Identity & KYC**, post-launch, enterprise tier):
  - V1 — decide integration: DigiLocker (official government), Signzy / Karza (commercial aggregators). Default DigiLocker + Aadhaar offline-XML.
  - V2 — PAN via NSDL CVL e-KYC.
  - V3 — OTP for contact verification (MSG91).
  - V4 — `ClientVerification` record: kyc_status ∈ {pending, verified, rejected}, aadhaar_verified_at, pan_verified_at, documents_json.
  - V5 — fraud-detection: reject if `pan.dob` ≠ `aadhaar.dob` (already surfaced by providers).
  - V6 — regulatory posture: this is legally sensitive. Bar Council practice rules may restrict lawyer-side KYC. Legal-review required before build.

---

## Cross-cutting blockers

- **Temporal (PRD §5.1)** — required for Calendar reminders (T), Notifications (T), AutoMail queueing (S), Clients communication log async fan-out (S). Not started. Start of Sprint T is blocked until Temporal is stood up.
- **Email provider** — SMTP is fine for alerts but production needs SendGrid / SES for deliverability + webhooks. Not provisioned.
- **SMS provider** — MSG91 or Twilio. Not provisioned.
- **Form builder library** — React Hook Form + Zod (standard MIT stack); no blocker.
- **PDF viewer** — `react-pdf` (MIT); no blocker.
- **Translation provider** — Haiku (already integrated); no blocker.
- **KYC aggregators** — DigiLocker + NSDL need enterprise agreement; legal review.

---

## Sprint assignment summary

New sprints added to `WORK_TO_BE_DONE.md`:

| Sprint | Covers MOD-TS | Weeks | Order |
|--------|---------------|------:|------:|
| P (active) | 001 | 1–4 | Now |
| Q — Document Intelligence UX | 002, 004, 005 | 3 | Next |
| R — Stepwise Drafting + Per-type Templates | 008, 012 | 3 | Next+1 |
| S — Clients & Comms | 009, 010 | 4 | After Temporal |
| T — Calendar & Notifications | 006, 007 | 3 | After Temporal |
| U — Legal Translator | 003 | 2 | v2 |
| V — Identity & KYC | 013 | 4 | Post-launch, enterprise |
| W — In-app Support | 011 | 1 | v2 |

Order: Q → R runs in parallel with P. S and T wait for Temporal (§5.1).
U / V / W deferred.

---

## Execution log — 2026-04-20 (evening)

Sequence agreed with user: **A1 deploy first**, then **Q4 OCR quality
gate + R1/R2 drafting templates in parallel**. Update this log as
items land. Earlier sprint shipments (P, Q1, Q5) are already reflected
in the status table above.

### Thread A — Production hygiene (unblock today's value)

- [x] **A1 — Deploy API + Web to Cloud Run — ✅ DONE 2026-04-20 evening.** HEAD `8a88bbd` live in `asia-south1`, 100 % traffic. New revisions: `caseops-api-00006-224` (from `-00005-xb8`) and `caseops-web-00008-9n5` (from `-00007-5xm`). Images: `caseops-api:8a88bbd` + `caseops-web:8a88bbd`. Smoke tests: `GET https://api.caseops.ai/api/health` → 200 OK; `GET https://caseops.ai/app/research` → 200; `GET /api/matters/.../bench-match` → 401 missing_bearer_token (proves the P3 route is mounted). No rollback needed. Also covers the later commits `b438982` (Q4 OCR gate) + `f0c5415` (R1/R2/R3) which landed before cutover — re-deploy required to push those, tracked below.
- [ ] **A1b — Redeploy after Q4 + R1/R2/R3 commits.** HEAD moved past `8a88bbd` → `34641a9` after the deploy. Next cutover should pick up `b438982` + `f0c5415` + `34641a9` so OCR quality gate and `GET /api/drafting/templates` reach prod.
- [ ] **A2 — Identify + close remaining Hari bugs.** 4 of 10 unaddressed.
- [ ] **A3 — Verify CI green** on commits `662de6a`, `8a88bbd`, `b438982`, `f0c5415`.

### Thread B — Sprint Q4 (OCR quality gate — prevents corpus poisoning) — ✅ DONE commit `b438982`

- [x] **Q4a** — per-page OCR confidence + length-normalised quality score emitted during extraction (rapidocr averages per-line `scores`; tesseract switches to `image_to_data` and averages per-word conf).
- [x] **Q4b** — `_apply_page_quality_gate` rejects pages with confidence < `ocr_min_page_confidence` (default 0.4) OR length < `ocr_min_page_chars` (default 50). Rejected pages stay in `OcrResult.pages` for telemetry; their text never reaches chunking.
- [x] **Q4c** — 7 unit tests in `test_ocr.py` (high-conf accepted, low-conf rejected, too-short rejected, mixed 5-page doc keeps exactly 3, zero-conf rejected, thresholds configurable, `pages_rejected` + `reject_reason` surface). All 12 `test_ocr.py` tests green.

### Thread C — Sprint R1/R2 (stepwise drafting + per-type prompts) — ✅ R1/R2/R3 DONE commit `f0c5415`

- [x] **R1** — `apps/api/src/caseops_api/schemas/drafting_templates.py` with `DraftTemplateType` (8 values: bail, anticipatory_bail, divorce_petition, property_dispute_notice, cheque_bounce_notice, affidavit, criminal_complaint, civil_suit) + one Pydantic facts model per type, strict validation (cheque_amount_inr > 0, affidavit min paragraphs, civil suit ≥1 relief), `DraftingFieldSpec` UX metadata for the stepper.
- [x] **R2** — `apps/api/src/caseops_api/services/drafting_prompts.py` — one specialised prompt per type. Bail enforces BNSS s.483 + triple test + parity. Cheque Bounce hard-enforces the statutory 15-day window + amount in figures AND words. Criminal Complaint defaults to BNS with the 2024-07-01 cutover called out. Civil Suit flags Commercial Courts Act s.12A.
- [x] **R3** — `GET /api/drafting/templates` (list) + `GET /api/drafting/templates/{type}` (full schema + Pydantic JSON-schema for Zod). Wired at `/api/drafting/*`.
- [ ] **R7** — per-type fixture at `apps/api/tests/fixtures/drafting/{type}.json` with a golden draft. Deferred to a follow-up (the 18 tests in `test_drafting_templates.py` already cover schema + prompt gates; goldens belong in a dedicated `eval_drafting --type bail` pass which is its own sprint line-item).
