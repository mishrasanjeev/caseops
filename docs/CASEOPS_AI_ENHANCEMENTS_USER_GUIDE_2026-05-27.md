# CaseOps AI Enhancements User Guide

Date: 2026-05-27
Scope: AI recommendations, automated legal updates, and CNR/case-number case tracking.

This guide explains how to use and operate the CaseOps AI enhancement workflows added from `docs/PRD_CASEOPS_AI_ENHANCEMENTS_2026-05-26.md`.

## What Changed

CaseOps now has three new connected workflows:

1. Lawyer-thinking AI recommendations.
2. Automated legal update monitoring from configured legal update sources.
3. Provider-gated case tracking by CNR or case number.

All three workflows keep the same safety posture:

- AI output is for lawyer review.
- Source provenance is shown where available.
- Durable in-app notifications are used.
- External notification channels such as email, SMS, WhatsApp, and push are not enabled by this release.
- Provider-backed integrations remain disabled unless explicitly configured.
- Captcha-gated or session-gated official court pages are not scraped.

## Permissions And Access

The new workflows reuse existing CaseOps access boundaries.

Recommendations:

- Users need recommendation generation access for the matter.
- Matter access rules still apply.
- Review and decision controls remain unchanged.

Legal updates:

- Users with statute or authority search access can view legal update surfaces.
- Source sync is an admin/source-manager action.
- Watchlist notifications are scoped to users who are allowed to receive the update in the current company, matter, or contract context.

Case tracking:

- Users need authority search access.
- Matter-linked bookmarks also enforce matter visibility.
- Polling jobs run server-side and create notifications only inside the same tenant/company scope.

## Lawyer-Thinking AI Recommendations

### Where To Find It

Open a matter, then go to the recommendations page:

`Matters -> selected matter -> Recommendations`

The page now includes a textarea above the generation controls:

`What are you thinking or planning for this matter?`

Example:

`I am planning to skip filing a reply on the next hearing date.`

### How To Use It

1. Open the matter recommendations page.
2. Optionally enter the lawyer's planned action, assumption, concern, or strategy.
3. Select the recommendation objective as usual, or leave the objective independent from the textarea.
4. Generate one of the available recommendation types:
   - Authority.
   - Forum.
   - Remedy.
   - Next best action.
5. Review the structured analysis block on each recommendation card.
6. Use the existing accept, edit, defer, or reject decision controls.

### What The Output Contains

Each generated recommendation can include:

- Recommendation.
- Risk analysis.
- Legal impact.
- Suggested actions.
- Confidence score.
- Confidence explanation.
- Verified citations.
- Review-required warnings.

The language is intentionally framed as possible actions for lawyer review. The system should not provide final legal advice or success probabilities.

### What Happens If The Textarea Is Blank

If the lawyer-thinking field is blank, CaseOps still generates recommendations from bounded matter intelligence context, including available matter metadata, recent hearings, court orders, statute references, attachment summaries, activity timeline items, and retrieved authorities.

### Privacy And Audit Behavior

CaseOps does not persist the raw lawyer-thinking text in a dedicated recommendation column.

Audit metadata stores only:

- Whether lawyer-thinking text was present.
- A SHA-256 digest.
- Text length.
- Source marker such as `lawyer_thinking` or `custom_goal`.

Prompt hashes, provider, and model metadata continue to be tracked through model-run audit records without storing raw prompt content.

### Compatibility Notes

The older `custom_goal` behavior remains supported. If both fields are present, the lawyer-thinking field is treated as the preferred custom objective text.

## Automated Legal Updates

### Where To Find It

Open:

`Statutes -> Legal updates`

The statutes surface now includes:

- Latest legal updates.
- Source/provenance badges.
- Source-backed summaries.
- In-app-only delivery labels.
- Watchlist matching results.
- Amendment history links where a statute is matched.

On a statute detail page, an amendment history section shows durable change events for that Act.

### Source Sync

The first configured source is PRS Acts of Parliament:

`https://prsindia.org/acts/parliament`

The source sync stores normalized source records instead of relying only on manual watchlist runs. Each source record tracks:

- Source key.
- Stable source record key.
- Update type.
- Title and normalized title.
- Source URL and document URL.
- Published and effective dates when available.
- Matched statute and sections when detectable.
- Content hash.
- Provenance status.
- Summary status.
- First seen, last seen, and updated timestamps.

Repeated syncs are idempotent. A source record is matched by source key plus stable source record key, and content changes are detected through the content hash.

### Running Source Sync

Admin/source-manager users can run source sync from the UI when the button is shown.

Operators can also run the console script:

```powershell
uv --directory apps/api run caseops-sync-legal-updates
```

The scheduled job path respects the legal update sync settings. In local development, manual invocation is enough.

Relevant settings:

- `CASEOPS_LEGAL_UPDATE_SYNC_ENABLED`
- `CASEOPS_LEGAL_UPDATE_PRS_BASE_URL`
- `CASEOPS_LEGAL_UPDATE_SYNC_DEFAULT_LIMIT`
- `CASEOPS_LEGAL_UPDATE_SYNC_FREQUENCY`
- `CASEOPS_LEGAL_UPDATE_SUMMARY_ENABLED`

### Watchlists

Existing legal update watchlists continue to work.

Watchlist matching now checks source records first, then falls back to the existing statute/authority matching behavior for backward compatibility.

Watchlists can match by:

- Source key.
- Source category.
- Statute.
- Statute terms.
- Update type.
- Matter scope.
- Contract scope.

When a matching run creates alerts, it also creates durable in-app notification intents for relevant recipients. Duplicate runs should not create duplicate alerts or notification intents for the same match.

### Summaries

Legal update summaries include:

- Plain-English summary.
- Affected Acts.
- Affected sections when detectable.
- Change kind.
- Practical legal impact.
- Suggested lawyer review actions.
- Confidence.
- Source URL.
- Provenance status.

If AI summary generation fails, the source record is still saved and marked as failed. Watchlist notifications can still use deterministic fallback text.

### Amendment History

Matched legal update source records can create durable statute change events.

Open a statute detail page and review the amendment history section to see:

- Change type.
- Title.
- Sections changed.
- Summary.
- Comparison metadata when available.
- Published and effective dates.
- Source URL.

### Notification Behavior

Legal update notifications are in-app only.

Recipient rules are scoped by the watchlist:

- Matter-linked watchlists notify users with matter access.
- Contract-linked watchlists notify users with contract visibility where available.
- Company-wide watchlists notify active internal company users.
- Outside-counsel users are not notified for company-wide statutory updates unless they have explicit matter or portal access.

## CNR And Case-Number Tracking

### Where To Find It

Open:

`Case tracking`

The sidebar now includes a Case tracking entry.

Matter hearing pages may also show a Track this court case panel, which can create a bookmark linked to the matter.

### Provider Configuration

Case tracking is provider-gated. By default it is disabled.

Relevant settings:

- `CASEOPS_CASE_TRACKING_ENABLED`
- `CASEOPS_CASE_TRACKING_PROVIDER`
- `CASEOPS_ECOURTSINDIA_API_BASE_URL`
- `CASEOPS_ECOURTSINDIA_API_TOKEN`
- `CASEOPS_CASE_TRACKING_POLL_LIMIT`
- `CASEOPS_CASE_TRACKING_DEFAULT_POLL_INTERVAL_HOURS`

CaseOps does not scrape captcha-gated or session-gated eCourts pages. The eCourtsIndia integration is treated as a provider-gated API integration. If the provider is not configured, the UI shows a disabled state and search/polling should not call the provider.

### Searching For A Case

Users can search by:

- CNR number.
- Case number.
- Optional court, state, or court code filter.

The search form validates the input and returns normalized provider results when the provider is configured.

Each result can show:

- Case title.
- Court.
- Current status.
- Stage.
- Next hearing.
- Provider/provenance labels.

### Creating A Bookmark

After selecting a search result, create a bookmark.

Bookmarks store:

- Company scope.
- Tracked case identity.
- Bookmark owner.
- Optional matter link.
- Display name.
- Notification preference.
- Archive state.

CaseOps prevents duplicate active bookmarks for the same user, tracked case, and matter scope.

### Bookmark List

The Case tracking page shows active bookmarks with:

- Current status.
- Current stage.
- Next hearing.
- Last checked time.
- Notification toggle.
- Refresh action.
- Archive action.

Archived bookmarks are excluded from the active list.

### Manual Refresh

Use the bookmark refresh action to fetch a new provider snapshot for that tracked case.

Refresh detects:

- New orders.
- New final judgments.
- Hearing date changes.
- Status changes.
- Case metadata changes.

Detected updates are stored once by tracked case, source record key, and update type.

### Polling Job

Operators can run the polling script:

```powershell
uv --directory apps/api run caseops-poll-tracked-cases
```

The job:

- Respects `CASEOPS_CASE_TRACKING_ENABLED`.
- Groups active bookmarks by tracked case.
- Polls each tracked case at most once per run.
- Enforces the configured poll limit.
- Uses provider bulk refresh when available.
- Continues after per-case provider failures.
- Records poll metrics and audit events.

### Case Update Summaries

For new orders or judgments, CaseOps can generate a bounded summary with:

- Concise summary.
- Procedural impact.
- Next hearing or action signals.
- Risks and unknowns.
- Source reference.
- Confidence.

If a provider supplies an AI summary, CaseOps stores it only when terms permit and marks the summary source as provider. Otherwise CaseOps uses its own LLM path when source text is available. If no text is available, deterministic fallback text is used.

### Notification Behavior

Case tracking notifications are in-app only.

Notification events include:

- `case_tracking.new_order`
- `case_tracking.new_judgment`
- `case_tracking.hearing_updated`
- `case_tracking.status_changed`

Users receive notifications only for bookmarked cases where notifications are enabled and access rules allow it.

## Operational Checklist

Before enabling scheduled jobs in an environment:

1. Confirm database migrations have been applied.
2. Confirm provider settings are present only in environment variables or secret storage.
3. Confirm legal update source sync is enabled only where intended.
4. Confirm case tracking provider terms permit the configured usage.
5. Confirm no external notification channel is enabled for these workflows.
6. Run one manual source sync or polling run in a non-production environment.
7. Review audit events and notification delivery intents.

## Console Scripts

Legal update sync:

```powershell
uv --directory apps/api run caseops-sync-legal-updates
```

Tracked case polling:

```powershell
uv --directory apps/api run caseops-poll-tracked-cases
```

Both scripts are intended for scheduler integration outside the web request path.

## Troubleshooting

### Recommendation Did Not Include Analysis Sections

Check that the response includes the `analysis` object. Older cached or pre-existing recommendations may not have structured analysis JSON.

### Recommendation Has No Citations

Citation verification remains fail-closed. Recommendations without verified citations should preserve the existing no-citations-survived behavior and should not be treated as source-backed.

### Legal Update Sync Creates No Records

Check:

- Source sync enabled state.
- PRS base URL.
- Network/provider availability.
- Sync run status and error message.
- Source adapter parser assumptions.

### Repeated Legal Update Sync Creates Duplicates

This should not happen. Check the uniqueness constraint on `(source_key, source_record_key)` and inspect whether the adapter is generating unstable source record keys.

### Case Tracking Search Is Disabled

This is expected unless case tracking is enabled and the eCourtsIndia provider base URL and token are configured.

### Polling Does Not Create Updates

Check:

- Active bookmarks exist.
- Bookmark notification is enabled.
- Provider is configured.
- Snapshot hashes changed.
- Update source record keys are new.
- Poll run errors are redacted but available in operational logs.

### Notifications Are Not Sent Externally

This is expected. These workflows enqueue durable in-app delivery intents only. External delivery remains outside the scope of this release.

## Safety Notes

- Do not enter confidential strategy text into environments that are not approved for AI processing.
- Do not configure provider tokens in frontend code.
- Do not use scraped court pages behind captcha or session gates.
- Treat summaries as source-backed drafting aids for lawyer review, not final legal advice.
- Review all AI-generated content before acting on it.
