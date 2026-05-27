# PRD: CaseOps AI Enhancements

Status: implementation-ready draft for Codex CLI
Date: 2026-05-26
Source document: `C:\Users\mishr\Downloads\CaseOps_AI_Enhancement_Requirements.docx`
Target repo: `C:\Users\mishr\caseops`

## 1. Purpose

Implement the three CaseOps enhancement areas from the source document end to
end:

1. AI recommendations driven by a lawyer's own thinking, planned action,
   assumption, concern, or strategy.
2. Automated legal update and amendment monitoring, initially from PRS India
   Acts/Parliament update sources, with AI summaries, Act-level change history,
   and in-app notifications.
3. Case/judgment tracking by CNR or case number, with bookmarks, polling,
   update detection, AI summaries, and notifications to bookmarked users.

This PRD is written so Codex CLI can implement directly against the current
CaseOps full-stack app.

## 2. Source Document Extraction Notes

Structural DOCX extraction was performed on 2026-05-26.

- Full text was extracted from all paragraphs.
- No literal Word highlight markup was present (`w:highlight = 0`).
- No paragraph shading was present (`w:shd = 0`).
- No comments file was present.
- No tracked insertions or deletions were present.
- The "highlighted points" are therefore interpreted as all stated proposed
  enhancements, bullets, external integrations, and business benefits in the
  document.
- LibreOffice render QA could not be completed in this environment because the
  renderer binary was unavailable. The OOXML structure was still inspected
  directly.

## 3. Current Repo Alignment

| Area | Existing foundation | Gap to close |
| --- | --- | --- |
| AI recommendations | `apps/api/src/caseops_api/services/recommendations.py` already supports recommendation types, objective contexts, `custom_goal`, citation verification, audit logs, and review-required outputs. UI is in `apps/web/app/app/matters/[id]/recommendations/page.tsx`. | The UI exposes "Custom goal" only as an objective, not the requested always-visible lawyer-thinking field. Backend prompt uses matter metadata and authorities but not enough case history/doc/order/statute context. Output does not expose dedicated `Recommendation`, `Risk Analysis`, `Legal Impact`, `Suggested Actions`, and `Confidence Score` sections. |
| Legal updates | `apps/api/src/caseops_api/services/legal_updates.py`, `schemas/legal_updates.py`, `api/routes/statutes.py`, and `apps/web/app/app/statutes/page.tsx` implement manual in-app watchlists against existing statute/authority records. | No PRS/Parliament ingestion. No scheduled sync. No persistent external source records. No Act amendment/change history. No AI summaries/comparisons. Existing "in-app records" are not durable notification delivery intents for all relevant users. |
| Judgment alerts | `apps/api/src/caseops_api/services/judgment_alerts.py`, `api/routes/authorities.py`, and `apps/web/app/app/research/page.tsx` implement manual deterministic rules over existing `AuthorityDocument` rows. | No CNR/case-number search. No case bookmarks. No eCourts provider adapter. No polling/update detection. No case-status/order snapshot history. No AI summary for newly released orders/judgments. No automatic notifications to bookmark owners. |
| Court sync | `services/court_sync_sources.py` and `services/court_sync_jobs.py` already sync selected court public pages into matter cause-list/order surfaces. | Existing court sync is matter/page based, not user-bookmarked CNR tracking. Do not overload it for CNR watchlists; reuse patterns where useful. |
| Notifications | `services/notification_delivery.py`, `services/notification_rules.py`, and `api/routes/notifications.py` provide durable in-app delivery intents, blocked external delivery, retry/dead-letter state, and admin visibility. | Legal update and case tracking alerts should use this foundation instead of only local alert rows. External email/SMS/WhatsApp remains out of scope unless a later task explicitly enables provider delivery. |

## 4. Product Goals

- Let lawyers ask CaseOps, "Here is what I am thinking. What are the risks,
  legal impact, better alternatives, and next steps?"
- If the lawyer provides no free-text thinking, generate recommendations from
  matter details, court history, documents, statutes, previous orders, and
  similar authorities.
- Track legal changes without requiring a user to manually run watchlists.
- Give users source-backed, human-readable summaries of legal updates and new
  case events.
- Let users bookmark a case by CNR or case number and receive in-app
  notifications when the case changes.
- Keep all AI output review-required, citation/source-backed, tenant-scoped,
  auditable, and safe for lawyer review.

## 5. Success Metrics

- Recommendation usefulness: at least 70 percent of generated
  lawyer-thinking recommendations receive an accept/edit/defer decision rather
  than immediate rejection in seeded QA workflows.
- Recommendation coverage: 100 percent of generated recommendations render the
  five required analysis sections.
- Legal update freshness: PRS source sync can run daily or weekly and records
  `last_seen_at` for each source record.
- Legal update engagement: users can open a legal update, view source
  provenance, and mark it read/dismissed without leaving the Statutes surface.
- Case tracking latency: scheduled polling detects fixture-based new
  orders/status changes within one poll run.
- Notification reliability: duplicate sync/poll runs do not create duplicate
  in-app notifications.
- Safety: no external notification channel is enabled, no captcha-gated source
  is scraped, and no recommendation is saved without verified citations.

## 6. Non-Goals

- Do not implement external email/SMS/WhatsApp/push delivery in this PRD.
  Create in-app delivery intents only; non-in-app channels remain blocked by
  the existing notification delivery policy.
- Do not scrape captcha-gated or session-gated court pages.
- Do not make outcome predictions, success probabilities, judge-shopping
  recommendations, or final legal advice.
- Do not expose raw external provider payloads to users.
- Do not notify users outside their tenant or outside matter access boundaries.
- Do not rewrite the existing recommendation, legal update, judgment alert, or
  court sync systems from scratch.

## 7. External Source Assumptions

Verified source references checked on 2026-05-26:

- PRS has an Acts of Parliament index at
  `https://prsindia.org/acts/parliament`.
- The official eCommittee eCourts services page describes cause lists, case
  status, daily orders, and final judgments accessible by CNR, case number,
  court number, party name, and order date:
  `https://ecommitteesci.gov.in/service/ecourts-services-portal/`.
- `https://ecourtsindia.com/api/docs` is a non-government provider API that
  documents CNR case detail, order PDF, AI order summary, case search, cause
  list, refresh, and bulk refresh endpoints. Use it only behind an explicit
  provider adapter, token setting, and terms/licensing gate.

Default implementation decision:

- PRS ingestion may ship first using public PRS pages as source metadata.
- Case tracking must be provider-adapter based. If no lawful provider token is
  configured, the UI must show a disabled/needs-configuration state and no
  polling should run.

## 8. Permissions And Delivery Rules

- AI recommendation generation keeps `recommendations:generate`.
- Strategy-specific actions keep `strategy:generate` and `strategy:approve`.
- Legal update watchlist/source management uses `authorities:search` for read
  and create/run, matching the existing route gate. If admin-only source
  operations are added, gate them behind `notifications:manage` or a new
  `legal_updates:manage` capability.
- Case tracking create/bookmark/read uses `authorities:search` plus matter
  access when linked to a matter. Polling jobs run system-side but must enforce
  tenant boundaries when creating notifications.
- Legal update notifications go to active tenant memberships with relevant
  access and no opt-out. For v1, "all users" means all active internal company
  memberships with platform access, not every global CaseOps user.
- Case update notifications go to users who bookmarked the case and, when the
  bookmark is matter-linked, members who can access the matter and have the
  bookmark notification enabled.

## 9. Epic A: Lawyer-Thinking AI Recommendations

### A1. User Story

As a lawyer, I can type what I am thinking or planning for a matter, such as
"I am planning to skip filing a reply on the next hearing date," and receive
source-backed AI decision support that explains:

- Recommendation.
- Risk analysis.
- Legal impact.
- Suggested actions.
- Confidence score.

If I leave the text blank, CaseOps generates recommendations from the matter
record, prior documents, case history, court orders, statutes, and similar
cases.

### A2. UX Requirements

Modify `apps/web/app/app/matters/[id]/recommendations/page.tsx`.

- Add an always-visible textarea above the generate buttons:
  - Label: `What are you thinking or planning for this matter?`
  - Placeholder: `Example: I am planning to skip filing a reply on the next hearing date.`
  - Max length: 1200 characters.
  - Data test id: `recommendation-lawyer-thinking`.
- Keep the existing Objective selector, but rename `Custom goal` to
  `Lawyer thinking` only if it remains in the dropdown. Preferred v1 behavior:
  keep objective optional and independent from the textarea.
- When textarea has text, send it to the backend for all recommendation types:
  `authority`, `forum`, `remedy`, `next_best_action`.
- When textarea is empty, send no lawyer-thinking payload. Backend must use
  fallback matter intelligence.
- Render a dedicated analysis block in each recommendation card with labels:
  `Recommendation`, `Risk analysis`, `Legal impact`, `Suggested actions`,
  `Confidence score`.
- Preserve the existing review-required disclaimer and decision controls.
- Preserve citation chips and "no citations survived verification" behavior.

### A3. API And Schema Requirements

Modify:

- `apps/api/src/caseops_api/schemas/recommendations.py`
- `apps/api/src/caseops_api/api/routes/recommendations.py`
- `apps/api/src/caseops_api/services/recommendations.py`
- `apps/web/lib/api/endpoints.ts`
- `apps/web/lib/api/schemas.ts`

Backend request:

- Add `lawyer_thinking: str | None = Field(default=None, max_length=1200)`.
- Keep `custom_goal` for backward compatibility.
- If `lawyer_thinking` is provided, treat it as the preferred custom objective
  text.
- If only `custom_goal` is provided, keep current behavior.
- If neither is provided, use automatic matter context.

Backend response:

- Add optional structured field to `RecommendationRecord`:

```json
{
  "analysis": {
    "recommendation": "string",
    "risk_analysis": ["string"],
    "legal_impact": ["string"],
    "suggested_actions": ["string"],
    "confidence_score": "low|medium|high",
    "confidence_explanation": "string"
  }
}
```

Persistence:

- Add nullable `analysis_json` column to `Recommendation`.
- Do not store raw lawyer-thinking text in a dedicated column unless product
  explicitly asks later. Audit metadata should store only:
  - present boolean
  - SHA-256 digest
  - length
  - source: `lawyer_thinking` or `custom_goal`
- ModelRun already stores prompt hash/provider/model; keep raw prompt content
  out of the database.

### A4. Matter Intelligence Context

When lawyer-thinking text is blank, or as supporting context when it is
present, backend prompt assembly must include bounded context from:

- Matter title, parties, practice area, forum, court, judge, status, next
  hearing, and description.
- Recent `MatterHearing` rows.
- Recent `MatterCourtOrder` summaries and order text excerpts.
- Linked `MatterStatuteReference` sections.
- Processed matter attachment summaries/snippets where available.
- Existing retrieved authorities from the recommendation retrieval pipeline.
- Existing `MatterActivity` timeline items where relevant and bounded.

Implementation guidance:

- Build a helper such as `_build_matter_intelligence_context(session, matter)`.
- Keep each source bounded; never dump full documents into prompts.
- Use deterministic truncation and include source labels in the prompt.
- Add unit tests that verify court orders/statute references appear in the
  prompt context without leaking unrelated tenant data.

### A5. AI Prompt Requirements

Update `_build_prompt` in `services/recommendations.py`.

- Preserve current citation rules and fail-closed citation verification.
- Include `LAWYER_THINKING` only when provided.
- Include `MATTER_INTELLIGENCE_CONTEXT` always.
- Add output schema fields for the analysis object.
- Instruct the model:
  - Analyze risks, benefits, legal implications, and alternatives.
  - Use "possible actions for lawyer review" language.
  - Never state that the lawyer "should" perform the action.
  - If the planned action is risky, identify safer alternatives.
  - If evidence is insufficient, lower confidence and name missing facts.

### A6. Acceptance Criteria

- A lawyer can enter text in the new field and generate each recommendation
  type.
- The backend records only hashed lawyer-thinking metadata in audit logs.
- If the field is empty, recommendation generation still works from automatic
  matter intelligence context.
- The output card clearly shows Recommendation, Risk analysis, Legal impact,
  Suggested actions, and Confidence score.
- Existing custom-goal tests continue to pass.
- Unsafe lawyer-thinking text is rejected with the existing 422 safety pattern.
- No recommendation is saved without at least one verified citation.

### A7. Tests

Backend:

- Extend `apps/api/tests/test_recommendations.py`.
- Add tests for `lawyer_thinking` request normalization.
- Add prompt context test for court orders/statute references.
- Add safety rejection test for prohibited lawyer-thinking text.
- Add response serialization test for `analysis`.

Frontend:

- Extend `apps/web/app/app/matters/[id]/recommendations/page.test.tsx`.
- Assert textarea is visible.
- Assert generate sends `lawyerThinking` when filled.
- Assert generate omits it when blank.
- Assert analysis sections render.

## 10. Epic B: Automated Legal Updates And Amendment Notifications

### B1. User Story

As a CaseOps user, I receive in-app notifications when new Acts,
amendments, ordinances, notifications, repeals, or important legal updates are
published by configured legal sources. I can open a source-backed AI summary,
see affected Acts/sections, and inspect the amendment history for an Act.

### B2. Source Ingestion Design

Add source-level ingestion instead of relying only on manual watchlist runs.

New files:

- `apps/api/src/caseops_api/services/legal_update_sources.py`
- `apps/api/src/caseops_api/scripts/sync_legal_updates.py`

Settings in `apps/api/src/caseops_api/core/settings.py`:

- `legal_update_sync_enabled: bool = False`
- `legal_update_prs_base_url: str = "https://prsindia.org"`
- `legal_update_sync_default_limit: int = 100`
- `legal_update_sync_frequency: str = "daily"` with allowed values
  `daily|weekly`; this is consumed by deployment/runbook scheduling and does
  not create an in-process scheduler.
- `legal_update_summary_enabled: bool = True`

Source adapters:

- `PrsActsParliamentAdapter`
  - Fetch `https://prsindia.org/acts/parliament`.
  - Parse Act title, source URL, year, available metadata, and linked document
    references.
  - Compute a stable `source_record_key` from source key plus source URL/title.
  - Compute `content_hash` from canonical parsed metadata and text snippet.
- Future adapters should implement the same interface, not modify watchlist
  matching directly.

### B3. Data Model

Add Alembic migration after the current head.

New tables:

`legal_update_source_runs`

- `id`
- `source_key`
- `status`: `completed|failed|partial`
- `started_at`, `completed_at`
- `fetched_count`, `created_count`, `changed_count`
- `error_message`
- `metadata_json`

`legal_update_source_records`

- `id`
- `source_key`
- `source_record_key` unique per source
- `update_type`: `act|amendment|ordinance|notification|repeal|regulation|circular|order|practice_direction`
- `title`
- `normalized_title`
- `source_url`
- `source_document_url`
- `published_date`
- `effective_date`
- `act_year`
- `statute_id` nullable
- `statute_section_ids_json`
- `sections_changed_json`
- `source_category`
- `provenance_status`
- `content_hash`
- `raw_metadata_json`
- `summary_json` nullable
- `summary_status`: `pending|completed|failed|not_required`
- `model_run_id` nullable
- `first_seen_at`, `last_seen_at`, `updated_at`

`statute_change_events`

- `id`
- `statute_id`
- `source_record_id`
- `change_type`: `new_act|amendment|repeal|notification|unknown`
- `title`
- `sections_changed_json`
- `summary`
- `comparison_json`
- `published_date`
- `effective_date`
- `source_url`
- `created_at`

Extend `legal_update_alerts`:

- Add nullable `source_record_id`.
- Add nullable `summary_json` or include source record summary in response.

### B4. Matching And Watchlist Behavior

Update `services/legal_updates.py`.

- Watchlists should match against `legal_update_source_records` first.
- Existing statute/authority matching remains as fallback and for backward
  compatibility.
- Deduplicate by `source_record_key`.
- Existing `source_record_key` uniqueness remains valid.
- When `preview_only=false`, creating a `LegalUpdateAlert` should also enqueue
  in-app delivery intents for relevant recipients.

Recipient logic:

- If watchlist has `matter_id`, notify users with matter access.
- If watchlist has `contract_id`, notify users with contract visibility where
  available; otherwise internal company users only.
- If no matter/contract scope, notify active internal company memberships.
- Never notify outside-counsel users for company-wide statutory updates unless
  they have explicit matter/portal access.

### B5. AI Summary And Comparison

Add a summary helper in `legal_update_sources.py`.

Each source record summary should include:

- Plain-English summary.
- Affected Act(s).
- Affected section(s), if detectable.
- Change kind: new Act, amendment, repeal, notification, ordinance, or unknown.
- Practical legal impact.
- Suggested lawyer review actions.
- Confidence: low/medium/high.
- Source URL and provenance status.

Rules:

- If LLM fails, keep the source record and mark `summary_status=failed`.
- Watchlist notifications can still be created with deterministic title/snippet.
- Summary prompt must not provide legal advice or claim completeness.
- All summaries must include "source-backed summary for lawyer review" framing.

### B6. API Requirements

Extend `api/routes/statutes.py` or add a dedicated router if cleaner.

New/updated endpoints:

- `POST /api/statutes/legal-updates/sources/{source_key}/sync`
  - Admin/source-manager endpoint for manual sync.
  - Returns run record.
- `GET /api/statutes/legal-updates/source-records`
  - Filter by source, update type, date, statute, status.
- `GET /api/statutes/{statute_id}/amendment-history`
  - Returns `statute_change_events`.
- Existing:
  - `GET /api/statutes/legal-updates`
  - `GET /api/statutes/legal-updates/digest-preview`
  - `POST /api/statutes/legal-updates/watchlists/{id}/run`
  should include source-record summaries when available.

### B7. Jobs

Add console script in `apps/api/pyproject.toml`:

- `caseops-sync-legal-updates = "caseops_api.scripts.sync_legal_updates:main"`

Job behavior:

- Respect `legal_update_sync_enabled`.
- Support both daily and weekly scheduling from the deployment layer. In local
  development, manual invocation of the console script is sufficient.
- Pull configured sources.
- Upsert source records by `(source_key, source_record_key)`.
- Detect new/changed records by `content_hash`.
- Create or update `statute_change_events` when mapped to a statute.
- Run active watchlists after ingestion.
- Enqueue in-app notification delivery intents.
- Produce audit events:
  - `legal_update.source_sync_started`
  - `legal_update.source_record_created`
  - `legal_update.source_record_changed`
  - `legal_update.watchlist_matched`
  - `legal_update.notification_enqueued`

### B8. Frontend Requirements

Modify `apps/web/app/app/statutes/page.tsx`.

- Keep current watchlist UI.
- Add a "Latest legal updates" panel showing source records and summaries.
- Add source/provenance badges.
- Add "Run source sync" button only for users with the chosen admin/source
  capability.
- Show `In-app only` delivery status.
- Link each legal update to:
  - source URL
  - statute detail page if matched
  - Act amendment history if available
- On statute detail page (`apps/web/app/app/statutes/[statute_id]/page.tsx`),
  add "Amendment history" section backed by the new endpoint.

### B9. Acceptance Criteria

- A source sync creates source records from PRS Acts Parliament.
- Running sync twice does not duplicate records.
- Changing content hash creates a changed event and updates `last_seen_at`.
- Active watchlists match source records automatically after sync.
- In-app notification delivery intents are created for relevant recipients.
- Legal update records show AI summary when available and deterministic
  fallback when not.
- Statute detail pages expose amendment/change history.
- Existing legal update watchlist tests still pass.

### B10. Tests

Backend:

- Extend `apps/api/tests/test_statutes_routes.py`.
- Extend or add `apps/api/tests/test_legal_updates.py`.
- Add source adapter parser tests with static HTML fixtures.
- Add sync idempotency tests.
- Add watchlist source-record matching tests.
- Add notification intent tests.
- Add summary failure fallback test.

Frontend:

- Extend `apps/web/app/app/statutes/page.test.tsx`.
- Extend `apps/web/app/app/statutes/[statute_id]/page.test.tsx`.
- Assert source records, summaries, history, run button gating, and in-app
  delivery labels.

## 11. Epic C: CNR/Case-Number Judgment Tracking And Bookmark Notifications

### C1. User Story

As a lawyer, I can search for a case by CNR number or case number, bookmark it,
and receive in-app notifications when new orders, judgments, hearing updates,
or status changes are detected.

Required data flow:

`Search case -> Bookmark -> Store CNR/case identity -> Scheduled polling -> Update detection -> AI summary generation -> Notification delivery`

### C2. Why This Is Separate From Existing Judgment Alerts

Existing `JudgmentAlertRule` matches saved filters against existing
`AuthorityDocument` records. The requested feature is case-specific, live
tracking by CNR/case number, with polling and update detection. It should be a
new case tracking surface that can optionally create authority records later.

### C3. Provider Adapter

New files:

- `apps/api/src/caseops_api/services/case_tracking_providers.py`
- `apps/api/src/caseops_api/services/case_tracking.py`
- `apps/api/src/caseops_api/schemas/case_tracking.py`
- `apps/api/src/caseops_api/api/routes/case_tracking.py`
- `apps/api/src/caseops_api/scripts/poll_tracked_cases.py`

Settings:

- `case_tracking_enabled: bool = False`
- `case_tracking_provider: str = "disabled"`
- `ecourtsindia_api_base_url: str | None`
- `ecourtsindia_api_token: str | None`
- `case_tracking_poll_limit: int = 50`
- `case_tracking_default_poll_interval_hours: int = 24`

Provider interface:

```python
class CaseTrackingProvider(Protocol):
    def search_cases(self, *, query: CaseSearchQuery) -> CaseSearchResult: ...
    def get_case_by_cnr(self, *, cnr: str) -> ProviderCaseSnapshot: ...
    def refresh_cases(self, *, cnrs: list[str]) -> ProviderBulkRefreshResult: ...
```

Provider rules:

- Do not call provider unless `case_tracking_enabled=true` and token/base URL
  are configured.
- No captcha/session-gated scraping.
- Normalize provider errors into user-safe messages.
- Log provider request metadata without party names or full raw payloads.
- Store raw payload only if explicitly necessary and tenant-scoped; preferred
  v1 stores normalized snapshots plus hashes.

### C4. Data Model

New tables:

`tracked_cases`

- `id`
- `company_id`
- `provider`
- `cnr_number` nullable
- `case_number` nullable
- `court_code` nullable
- `court_name`
- `case_title`
- `party_names_json`
- `current_status`
- `current_stage`
- `next_hearing_on`
- `last_snapshot_hash`
- `last_provider_checked_at`
- `last_provider_refresh_requested_at`
- `last_error`
- `metadata_json`
- Unique constraint on company plus provider plus normalized CNR/case identity.

`tracked_case_bookmarks`

- `id`
- `company_id`
- `tracked_case_id`
- `created_by_membership_id`
- `matter_id` nullable
- `name`
- `notification_enabled`
- `is_archived`
- `created_at`, `updated_at`, `archived_at`
- Unique active bookmark per user/tracked case/matter.

`tracked_case_updates`

- `id`
- `company_id`
- `tracked_case_id`
- `update_type`: `new_order|new_judgment|hearing_update|status_change|case_metadata_change`
- `source_record_key`
- `title`
- `summary`
- `ai_summary_json`
- `source_url`
- `order_date`
- `hearing_date`
- `previous_hash`
- `current_hash`
- `provider_metadata_json`
- `model_run_id`
- `created_at`
- Unique constraint on tracked case plus source record key plus update type.

Optional v1 if useful:

- `tracked_case_poll_runs` for operational visibility.

### C5. API Requirements

Add router to `apps/api/src/caseops_api/api/router.py`.

Endpoints:

- `POST /api/case-tracking/search`
  - Input: CNR or case number plus optional court/state/court code.
  - Output: normalized results.
- `POST /api/case-tracking/bookmarks`
  - Create bookmark from CNR/result, optionally linked to a matter.
- `GET /api/case-tracking/bookmarks`
  - List active bookmarks for current user/company.
- `PATCH /api/case-tracking/bookmarks/{bookmark_id}`
  - Rename, enable/disable notifications, archive.
- `POST /api/case-tracking/bookmarks/{bookmark_id}/refresh`
  - Manual refresh for one bookmark/tracked case.
- `GET /api/case-tracking/bookmarks/{bookmark_id}/updates`
  - List detected updates.

Response objects should include:

- Current case status.
- Last checked time.
- Next hearing date.
- New orders/judgments count.
- AI summary availability.
- Source/provenance/provider labels.

### C6. Update Detection

Each provider snapshot should be normalized into stable structures:

- Case metadata.
- Hearing history.
- Orders.
- Judgments.
- Status/stage.

Detection algorithm:

1. Fetch current snapshot.
2. Compute canonical hashes for case metadata, each order, each judgment, and
   each hearing/status event.
3. Compare to existing `tracked_cases.last_snapshot_hash` and existing
   `tracked_case_updates.source_record_key`.
4. Create update rows for:
   - New order.
   - New final judgment.
   - New hearing date or changed next date.
   - Changed case status/stage.
5. Generate AI summary for new order/judgment when text or provider summary is
   available.
6. Update `tracked_cases` current status fields.
7. Enqueue in-app notifications to bookmarked recipients.

### C7. AI Summary Requirements

For newly detected orders/judgments:

- Prefer official/provider source text if available and licensed.
- If provider supplies an AI summary, store it only if terms permit and mark
  `summary_source="provider"`.
- Otherwise use CaseOps LLM with purpose `case_tracking:update_summary`.
- Summary fields:
  - concise summary
  - procedural impact
  - next hearing/action signals
  - risks/unknowns
  - source reference
  - confidence
- Never infer outcomes beyond the order text.

### C8. Notifications

Use `services/notification_delivery.py`.

Event types:

- `case_tracking.new_order`
- `case_tracking.new_judgment`
- `case_tracking.hearing_updated`
- `case_tracking.status_changed`

Notification title examples:

- `New order detected for {case_title}`
- `Next hearing changed for {case_title}`
- `Case status updated for {case_title}`

Notification body:

- Max 500 chars.
- Include date, court, and short summary.
- Include source provenance.

Idempotency:

- Use company, recipient, event type, tracked case update id, and channel.
- Do not create duplicate in-app notifications on rerun.

### C9. Frontend Requirements

Add new page:

- `apps/web/app/app/case-tracking/page.tsx`

Add navigation entry:

- `apps/web/components/app/Sidebar.tsx`
  - Label: `Case tracking`
  - Icon: use existing lucide icon such as `Bell`, `Search`, or `Bookmark`.

Page UX:

- Search form:
  - CNR number input.
  - Case number input.
  - Optional court/state/court code input.
  - Search button.
- Results:
  - Case title.
  - Court.
  - Current status/stage.
  - Next hearing.
  - Bookmark button.
- Bookmarks list:
  - Active bookmarks with last checked, status, next hearing.
  - Refresh button.
  - Notification toggle.
  - Archive action.
- Updates list:
  - Type badge.
  - Date.
  - AI summary.
  - Source link.
  - Unread/read affordance if implemented.

Matter integration:

- Add optional "Track this court case" panel or button to
  `apps/web/app/app/matters/[id]/hearings/page.tsx`.
- When launched from a matter, bookmark should carry `matter_id`.

Disabled state:

- If `case_tracking_enabled=false` or provider is not configured, show an
  actionable disabled state and never call search endpoints.

### C10. Jobs

Add console script in `apps/api/pyproject.toml`:

- `caseops-poll-tracked-cases = "caseops_api.scripts.poll_tracked_cases:main"`

Job behavior:

- Respect `case_tracking_enabled`.
- Select active bookmarks grouped by `tracked_case_id`.
- Poll each tracked case at most once per run.
- Enforce `case_tracking_poll_limit`.
- Use provider bulk refresh when available.
- Record poll run metrics and audit events.
- Continue after per-case provider failures.
- Redact provider errors.

### C11. Acceptance Criteria

- User can search by CNR and bookmark a case.
- User can search by case number with court/court-code filter and bookmark a
  selected result.
- Bookmark list shows current status, stage, next hearing, last checked.
- Manual refresh detects a new order fixture and creates exactly one update.
- Poll job detects updates idempotently.
- New updates enqueue in-app notification intents for bookmark recipients.
- AI summary is generated for new order/judgment text and gracefully skipped
  when text is unavailable.
- Feature is disabled and safe when provider config is missing.
- Existing judgment alert rule behavior remains unchanged.

### C12. Tests

Backend:

- Add `apps/api/tests/test_case_tracking.py`.
- Provider disabled tests.
- CNR normalization tests.
- Search/bookmark create/list/update/archive tests.
- Snapshot hash and update detection tests.
- Idempotent notification intent tests.
- Poll job continuation after provider failure.
- Tenant isolation and matter-access tests.

Frontend:

- Add `apps/web/app/app/case-tracking/page.test.tsx`.
- Extend `apps/web/components/app/Sidebar.test.tsx`.
- Extend matter hearings page tests if adding matter integration.

E2E:

- Add one Playwright smoke test only after mock provider support exists.

## 12. Cross-Cutting Technical Requirements

### 11.1 AI Safety

- Reuse existing unsafe prompt/output filters for recommendations.
- Add purpose-specific LLM contexts:
  - `recommendation:{type}`
  - `legal_update:summary`
  - `case_tracking:update_summary`
- All AI-generated content must be review-required and source-backed.
- No output may include legal advice as final instruction, success odds,
  judge-shopping, or fabricated citations/source URLs.

### 11.2 Audit

Record audit events for:

- Lawyer-thinking recommendation generation with hashed input metadata.
- Legal source sync and source-record changes.
- Legal update watchlist matches and notifications.
- Case tracking searches, bookmark creation/update/archive, refreshes, detected
  updates, and notifications.

Redaction rule:

- Do not store full lawyer-thinking text, full provider case payloads, or full
  order text in audit metadata.

### 11.3 Security And Tenancy

- Every read/write query must filter by `company_id`.
- Matter-linked bookmarks must validate matter visibility using existing
  matter access helpers.
- Provider tokens live only in settings/env vars.
- No provider token is exposed to frontend.
- No scraping captcha/session-gated surfaces.
- External source URLs are displayed as provenance, not as trusted legal
  conclusions.

### 11.4 Performance

- Source sync and case polling run outside request/response where possible.
- Manual refresh endpoint may run synchronous provider fetch for a single case
  but must have timeouts.
- Bulk polling must batch provider calls when available.
- Keep LLM summary generation bounded and skip/mark failed on timeout.

### 11.5 Observability

- Add structured logs for sync/poll counts, created records, changed records,
  failed records, provider disabled state, summary failures, and notification
  intent counts.
- Reuse existing `ModelRun` for LLM summaries.
- Add tests for dead-letter/blocked external notification behavior only if new
  event types interact with non-in-app channels.

## 13. Implementation Order

Recommended order for Codex CLI:

1. Epic A backend schema/prompt/analysis changes.
2. Epic A frontend textarea and analysis rendering.
3. Epic A tests.
4. Legal update source records and migrations.
5. PRS adapter and source sync script.
6. Legal update watchlist matching and in-app notification intents.
7. Legal update frontend and tests.
8. Case tracking models, schemas, provider interface, disabled state.
9. Case tracking search/bookmark/manual refresh API.
10. Case tracking poll job and notifications.
11. Case tracking frontend and tests.
12. Final full verification.

## 14. Verification Commands

Run targeted tests as each slice lands:

```powershell
npm run lint:api
uv --directory apps/api run pytest apps/api/tests/test_recommendations.py
uv --directory apps/api run pytest apps/api/tests/test_statutes_routes.py
uv --directory apps/api run pytest apps/api/tests/test_case_tracking.py
npm run test --workspace @caseops/web -- app/app/matters/[id]/recommendations/page.test.tsx
npm run test --workspace @caseops/web -- app/app/statutes/page.test.tsx
npm run test --workspace @caseops/web -- app/app/case-tracking/page.test.tsx
npm run typecheck --workspace @caseops/web
```

Before final PR:

```powershell
npm run test:api
npm run test:web
npm run typecheck:web
```

Run Playwright only if the local stack is available:

```powershell
npm run test:e2e:app
```

## 15. Definition Of Done

- All three source-document enhancement areas are implemented.
- No literal source requirement is dropped:
  - lawyer thinking input
  - fallback automatic matter-based recommendations
  - risks, benefits/legal impact, alternatives, suggested actions, confidence
  - PRS legal update sync
  - daily/weekly job path
  - new Acts/amendments/repeals/notifications detection
  - AI summaries
  - in-app notifications
  - amendment history/change log
  - CNR/case-number search
  - bookmarks
  - periodic eCourts/provider checks
  - order/judgment/status/hearing update detection
  - AI judgment/order summaries
  - notification to bookmarked users
- Existing recommendation, legal update, research, court sync, and notification
  tests continue to pass.
- New tests cover disabled provider states and idempotency.
- External source calls are behind explicit adapters/settings.
- No external notification channel is silently enabled.
- UI communicates source/provenance, in-app-only delivery, and review-required
  AI status.

## 16. Codex CLI Starter Prompt

Use this prompt from the repo root:

```text
Read docs/PRD_CASEOPS_AI_ENHANCEMENTS_2026-05-26.md end to end. Implement the PRD in the recommended order. Preserve existing behavior and tests. Add migrations, backend services, API schemas/routes, frontend pages/components, jobs, notifications, and tests exactly as scoped. Do not enable external notification channels. Do not scrape captcha-gated sources. Use provider-disabled safe states where credentials are absent. Run the targeted verification commands as each slice lands and finish with the full backend/frontend test set where feasible.
```

## 17. Review Passes Completed For This PRD

Round 1: Source document completeness

- Extracted full DOCX paragraph text.
- Confirmed there were no literal highlights, comments, or tracked changes.
- Enumerated every requirement bullet and example from the source.

Round 2: Existing codebase fit

- Reviewed recommendation backend/frontend paths.
- Reviewed legal update service, schema, routes, frontend, and ADP-18 docs.
- Reviewed judgment alert service, schema, routes, frontend, and ADP-17 docs.
- Reviewed court sync provider patterns and notification delivery foundation.

Round 3: Gap analysis

- Identified that existing legal updates and judgment alerts are manual and
  in-app-only foundations.
- Identified that source ingestion, polling, provider adapters, AI summaries,
  and durable in-app notification integration are the main gaps.
- Chose additive designs that preserve existing APIs and tests where possible.

Round 4: Implementation readiness

- Added file-level implementation targets.
- Added migrations/data model requirements.
- Added API contracts.
- Added frontend requirements and test IDs.
- Added security, audit, source access, notification, and disabled-state rules.
- Added acceptance criteria and verification commands.
