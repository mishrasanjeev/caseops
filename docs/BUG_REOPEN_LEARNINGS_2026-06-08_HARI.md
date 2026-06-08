# Bug Reopen Learnings - Hari 2026-06-08

Source: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari08Jul2026 .xlsx`.

## Where I Went Wrong

1. I treated backend existence as product closure. Court-order compliance models, routes, and extraction runs existed, but the user path after uploading an order did not refresh or expose the extraction state on the hearings page.
2. I let an action render without matching the server permission boundary. The matter invoice PDF button appeared even when the backend route would reject the user, creating a visible broken control.
3. I accepted a rough PDF as "download works." Receipt downloads need safe filenames, professional labels, payment status, and a browser-verifiable download flow.
4. I mistook an authenticated `.ics` download for a Google Calendar connector. Google cannot subscribe to a cookie-protected feed; a real fix needs OAuth, encrypted token storage, provider-specific event upsert logic, tenant-scoped sync records, and fail-closed missing-config UI.
5. I relied too much on component/API tests. For reopened bugs, the regression must include Playwright coverage of the user-visible path before calling the issue fixed.
6. I treated "not completed" as "upcoming" for hearing workflows. Cancelled hearings are closed legal events: they must not drive `Matter.next_hearing_on`, reminders, dashboards, calendar sync, or upcoming lists, but they must remain visible in cancelled history with audit context.

## Permanent Rules

- After any create/upload mutation, invalidate every visible dependent query, not only the primary workspace query.
- Empty states must not hide background processing state. If a run exists but produced no rows, show status, skip reason, and a safe next action.
- A button must not render if the backend will always 403 that user. UI capability gates must match server gates.
- Download fixes must verify the browser download event, filename, response content type, and a durable backend audit/export record where applicable.
- Do not describe authenticated export URLs as external calendar subscriptions. Google/Outlook subscription claims require OAuth-backed provider calls or a public/tokenized feed that external calendar services can fetch.
- Connector fixes are not complete until provider operations, audit metadata, tenant scoping, missing-config behavior, and no-secret response checks cover the new provider.
- Hearing status transitions must reconcile all derived state: `next_hearing_on`, reminders, upcoming buckets, timeline grouping, calendar provider events, and activity/audit labels.
- Every Hari/Ram reopened bug batch gets a focused Playwright spec in addition to unit/API tests.

## Regression Anchors Added

- BUG-051: Hearings page shows court-order compliance extraction run status and can queue document processing for uploaded order documents.
- BUG-052: Matter billing hides invoice PDF download for users without invoice permission and verifies the receipt download filename/content path for authorized users.
- BUG-053: Google Calendar V1 is OAuth-gated, stores tokens encrypted, supports mock-provider CaseOps-to-Google hearing/task/deadline create/update sync, provider-event delete for cancelled hearings, durable replay foundations, provider operations visibility, and fail-closed `.ics` fallback when config is missing.
- Gmail/Google Workspace: Gmail mailbox V1 is OAuth-gated, stores tokens encrypted, imports metadata/snippets only, creates review-first attachment candidates, validates Pub/Sub webhook tokens, records provider-operation rows, and avoids raw body/token/payload exposure.
- Hearing cancellation: cancelled hearings leave upcoming buckets, clear or recompute `Matter.next_hearing_on`, cancel reminders, delete synced provider calendar events, and remain visible in cancelled history.
