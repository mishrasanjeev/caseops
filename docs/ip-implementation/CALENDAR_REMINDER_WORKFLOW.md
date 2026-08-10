# IP hearing, reminder, and calendar workflow (IPLF-025B)

IPLF-025B turns the shared-work foundation into the user-facing UJ-10 and
UJ-62 workflow. It continues to use `matter_hearings`, `hearing_reminders`,
`notification_delivery_intents`, and `calendar_event_syncs`; there is no
IP-private reminder queue, calendar table, or dispatcher. The published
shared-work contract is `IPLF-025B/2026-08-10`.

## Hearing and reminder contract

The IP hearing adapter records date, exact/session/unpublished time precision,
IANA timezone, forum, judge, physical/virtual/hybrid mode, location, HTTPS
meeting link, purpose, source reference, responsible membership, and attendee
memberships. Migration `20260810_0004` adds only the logistics missing from the
canonical hearing owner.

The UI requires a preview before confirmation. The preview names recipients,
channels, offsets, and whether scheduling is exact, session-based, or
date-based. Unknown time is anchored to the disclosed policy time (18:00 in
the hearing timezone by default); it is never represented as a hearing time.

Each offset, recipient, and channel produces an inspectable
`HearingReminder`. The durable notification owner retains recipient and
destination snapshots, fallback lineage, attempts, cancellation, and provider
outcomes. A permission or lifecycle change is revalidated before dispatch.
Rescheduling cancels queued schedules and intents before creating replacements;
cancellation removes previously selected provider copies.

## External calendar boundary

Outlook and Google Calendar use the existing connection and
`CalendarEventSync` owners. An IP hearing, task, or operational deadline is
resolved through the same access policy before sync. The provider payload is a
date-only convenience projection with:

- a stable `(connection, source_type, source_id)` identity;
- a neutral `CaseOps IP - Hearing|Task|Deadline` title;
- the CaseOps source link and source version; and
- private correlation properties for the docket and canonical source row.

Docket title, identifier, purpose, forum, notes, and task text are not copied
to the provider. Resync updates the existing provider event ID. Reschedule
updates only copies already selected by that user; cancel deletes those copies.
Provider failure is recorded on the sync row and never rolls back or mutates
the authoritative CaseOps hearing/date. Existing provider-event candidates
remain the review boundary for inbound edits; an external edit cannot write a
CaseOps hearing, task, or deadline.

## Verification

- `tests/test_shared_work_foundation.py` proves unpublished-time behavior,
  logistics, four inspectable channel schedules, six durable intents including
  critical fallbacks, IP target lineage, and reschedule supersession.
- `tests/test_google_calendar_sync.py` proves minimal redaction, stable provider
  IDs, repeat-sync deduplication, reschedule upsert, and cancellation delete.
- `apps/web/app/app/ip/page.test.tsx` proves every grouped action remains visible
  at 360 px and the reminder preview precedes confirmation.
- `tests/e2e/iplf-025b-calendar-workflow-2026-08-10.spec.ts` executes the dated
  API/UI/persistence journey against the current build.

External-provider approval and human pilot/UAT acceptance remain separate
gates. No real recipient, court, registry, filing, fee, or provider account is
used by the automated proof.
