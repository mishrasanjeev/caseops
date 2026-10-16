# IP Portfolio Renewal Tracker

This guide covers supplied application and renewal dates, in-app reminders and
the portfolio deadline tracker. Current release evidence and limitations are in
`docs/BUGFIX_IP_RENEWAL_TRACKER_2026-10-15.md`.

## Review And Edit Dates

1. Open **Intellectual Property**, then **Trademark portfolio**.
2. Find the record by mark or application number. Application Date and Renewal
   Due Date are default columns. On a phone they appear in the record layout.
   A blank date displays **Not set**.
3. Select the pencil action beside the record to open **Edit portfolio dates**.
4. Change either date independently. Clear a date only when it is not supported
   by the source record. Enter a meaningful reason for the audit history.
5. Select **Save dates**. Wait for confirmation, then reload to verify the saved
   value. A rejected save keeps the entered values and displays the API error.

An edit from an old browser tab is rejected when the record version changed.
Refresh the record before making a new decision. Do not repeatedly submit a
stale version. Read-only users do not receive the edit action; closed or
otherwise restricted records remain protected by the server.

Date labels distinguish missing, manual, imported-unverified and verified facts.
Entering a manual date does not verify its legal basis. CaseOps does not derive
a renewal date from an application date or turn an imported date into a legally
verified deadline. Original import values and unrelated record details remain
part of their existing history.

## Reminder Schedule

The reminder window begins one calendar month before the supplied renewal date
and ends on the renewal date, inclusive. It is not a fixed 30-day subtraction.

| Renewal Date | Reminder Window Begins |
| --- | --- |
| 24 October 2028 | 24 September 2028 |
| 1 March 2028 | 1 February 2028 |
| 31 March 2028 | 29 February 2028 |
| 31 March 2027 | 28 February 2027 |

The default cadence is daily at 09:00 in the configured workspace timezone.
The workspace configuration owns cadence and local delivery time; the tracker
shows the actual policy used. The current policy supports a cadence of one to
31 days. Only an authorized configuration user can change it.

1. Open **Intellectual Property** and select **Workspace configuration** with
   a user allowed to configure IP. If the workspace is not yet enabled, use
   its existing setup form instead. Read-only roles do not receive this action.
2. Review **Timezone**, **Renewal reminder cadence (days)** and **Renewal
   reminder local time**. Use `1` for daily reminders and choose the intended
   local time. Keep the existing provider and legal-calendar settings unless
   you are deliberately changing those integrations.
3. Select **Save configuration**. Saving a new configuration version resets
   its previous readiness tests and enablement. Complete the displayed tests
   and enablement appropriate to the workspace before relying on it again.
4. Reload the configuration and tracker. Verify the saved cadence, local time
   and timezone. Enabling manual IP does not enable provider automation.

A cadence-only save preserves existing asset types, jurisdictions, calendars,
notification channels and reviewed provider settings. It does not grant new
provider consent. Review a rejected configuration response before trying again.

The persistent worker discovers due work without an open browser. When a record
is added or corrected inside its reminder window, recovery produces one current
catch-up occurrence, not a burst of every missed historical day. Repeating the
same worker occurrence must not produce a duplicate notification. Dismissing a
notification does not cancel tomorrow's recurrence.

Changing the renewal date supersedes pending work for the old date. Removing it
cancels pending reminders and makes the record discoverable under Missing
Renewal Date. Closed, renewed or cancelled records stop their applicable
pre-renewal sequence. After the due date, the tracker shows Overdue; this does
not create a new legal deadline or automatically authorize a late filing.

## Use The Deadline Tracker

Select the calendar-clock action labelled **Deadline tracker view** in the
portfolio toolbar. Search for the record and choose a category:

- **Upcoming Renewals**: source renewal dates inside the configured horizon.
- **Reminders Active**: records inside their one-calendar-month reminder window.
- **Due Today**: reminder occurrences due on the current local date.
- **Overdue**: an applicable source date has passed.
- **Missing Renewal Date**: no usable source renewal date is recorded.
- **Failed Alerts**: the latest applicable delivery attempt needs recovery.

Each record shows its dates and source states, reminder start, next reminder,
timezone, cadence and delivery outcome. On smaller screens, scroll the table
horizontally to reach the remaining fields and the edit action. Search is
bounded and tenant-scoped; counts describe records the current user may read.

**Scheduled** means work is scheduled, not delivered. **Sent** describes a
confirmed occurrence, not completion of the entire recurring series. Check its
delivery timestamp alongside the next reminder. A failed attempt shows the
available safe error detail. Refresh the tracker after a worker cycle rather
than creating duplicate records to retry a notification.

In-app delivery is the core channel. It does not require an Outlook or Google
Calendar connection. External email/calendar delivery still depends on its
separate configured integration and consent. This feature does not enable an
unconfigured sender, provider, paid service or external calendar.

If the chosen delivery time falls inside quiet hours, delivery waits for the
quiet window to end, including the following morning. The original occurrence
remains in history. Missed occurrences are superseded rather than delivered as
a historical burst; current source dates and authorization are rechecked. Removing
quiet hours does not authorize a second notification on a date that already
has a confirmed receipt.

## Filters And Imports

The portfolio Columns selector controls date-column visibility. The additional
date-range filters, selected columns and supported renewal categories can be
retained through the existing saved-view and export workflows. Verify the
selected scope before exporting. Registry synchronization status is separate
from date completeness or reminder delivery.

Use explicit supported dates, preferably ISO `YYYY-MM-DD`, in an import. Native
Excel date cells retain their date meaning. Missing optional date columns or
blank optional dates do not by themselves invalidate an otherwise valid row.
An ambiguous or invalid value must be resolved from the source, not guessed.
Review the import's created, skipped and failed counts and retained original
rows before treating the upload as complete.

Larger imports continue in acknowledged batches of at most 50 rows. Keep the
review open while its counts advance; a staged import is not a completed one.
After an interrupted connection, open the existing import from history and
inspect its retained counts before using its creator-authorized recovery
action. Do not upload another copy or discard the original claim to retry it.

## Legal Deadline Controls Are Separate

A supplied-date reminder is not an approved legal-rule calculation. The Legal
deadline control requires an eligible company-selected active rule and active
working calendar. Empty, loading and failed lists have different recovery paths.
Do not activate a draft, untested or unapproved rule merely to populate a list.

The governance list may retain active or historical versions for review even
when they are not eligible for calculation. Independent review, source
provenance, testing, current company selection and server authorization remain
authoritative. A disabled calculation with a stated missing prerequisite is not
permission to bypass that prerequisite.

Check the full selected rule or calendar description beneath its control,
including version, jurisdiction, office, timezone where applicable and status.
The closed native selector may shorten a long caption; the wrapping description
retains the complete current choice. Colleague selectors likewise show the
selected name and email below the control. Changing or clearing the selection
updates or removes that description. A retained unavailable colleague is
historical context, not permission to make a new assignment to that person.

To move an existing IP hearing, change its reschedule date and select
**Reschedule**. Wait for the saved date to appear before leaving the page, then
reload when checking the result. Moving the date preserves the hearing's
existing time precision, exact time and timezone; it does not supply a missing
published time or confirm an unverified time automatically.

## Operational Acceptance

Before describing the feature as live, the release operator must retain the
migration and source pins, normal scheduler/worker configuration, complete local
Docker results, green canonical-main CI/security and exact-serving browser
acceptance. A queued job, successful deployment command or skipped browser
journey is not delivery or end-to-end certification.

All automated verification uses the no-paid-provider boundary. Production
mutation acceptance is restricted to the authorized test-legal workspace. This
guide does not authorize GBA test writes or another manual-IP entitlement grant.
