# Portfolio Import And Court Calendar

## Release Status

October 13 implementation guide. Fresh combined Docker acceptance, green CI,
canonical-main merge and deployed browser replay are still required. This guide
does not certify the current production build. Acceptance evidence is tracked
in `docs/BUGFIX_IP_CALENDAR_2026-10-13.md`.

## Import A Trademark Register

1. Open IP Portfolio, then Trademark Portfolio Import.
2. Select a UTF-8 CSV or XLSX file. The limits are 10 MB, 1,000 data rows,
   100 columns, 255 characters per header, 10,000 characters per text cell and
   10 MB of decoded source text. A compressed workbook cannot bypass the decoded
   limit by repeating large cells. Use the active XLSX sheet.
3. Select **Validate file**. This stages a preview; it does not create dockets.
4. Open **Source column mapping** and review source values, normalized fields,
   warnings and skipped rows. Recognized aliases are not mapped by position.
5. Leave safe duplicates set to **Skip**. Distinct application numbers with
   the same mark are separate records. An explicit existing-record link does
   not overwrite that record's particulars.
6. Select **Commit to portfolio**. The server rechecks the source, current
   tenant, identities and write authority. The saved commit key makes a replay
   idempotent; it is not a reason to automatically retry a failed mutation.
7. Read the created, linked, skipped, duplicate, warning and failed counts.
   Import history retains the actual result after reload. Open the saved
   docket from Portfolio to inspect it.

Large commits use at most 50 rows per request. A successful `202` response means
the job is still staged, not completed. The page displays acknowledged progress
and continues those successful batches until the persisted job is terminal.
It does not retry a failed mutation. After interruption, open the creator's
saved Import history and continue the retained claim; the server resolves the
claim key without exposing it or relying on browser storage. A changed workspace
context requires a refreshed, reviewed preview for pending rows. Previously
committed rows and their original provenance are preserved.

No individual source column is mandatory. A usable mark/title or application
identity is needed to create a useful record. Missing legal facts stay empty;
incomplete applications remain drafts, not filing-ready registrations. Where
jurisdiction/office are absent, only an unambiguous configured workspace value
can supply context. Otherwise the row reports missing workspace context.

## Supported Source Columns

| Source header | Handling |
| --- | --- |
| S.No. | Original source-row reference; not a unique legal identifier |
| Trademark | Canonical mark and docket title |
| Trademark Image | Retained source reference; no embedded-image extraction or automatic download |
| Application Date | Parsed source application date |
| Renewal Due Date | Unverified business source date, used for the internal alert |
| Applicant Name(s) | Supplied applicant text; punctuation does not invent separate parties |
| Class | All valid Nice class numbers, including `9, 36, and 42` |
| Application No. | Canonical application identity under its jurisdiction/office |
| Status | Retained source status; cannot forge a canonical lifecycle transition |
| Comment | Retained import source metadata |
| Takeover request | Retained source request metadata; no automatic execution |
| Name Change request | Retained source request metadata; no automatic recordal |
| Address Change request | Retained source request metadata; no automatic recordal |
| Internal Remarks | Creator-authorized import evidence; not copied to the docket's general response or alert |

Safe aliases include Application Number/App. No., Applicant/Owner/Proprietor,
Nice Class, Filing Date and Renewal Date. Case, spacing and harmless header
punctuation are normalized. Conflicting aliases become a visible row error;
identical repeated headers are rejected because their cells cannot be safely
distinguished.

Existing jurisdiction/country, office, specification/goods and services, agent,
registration/filing numbers, priority date and notes are recognized where
supported. Some remain source metadata rather than an executed legal action.
Unknown extra columns are retained and listed as unmapped; they do not create
database columns. The preview records how every supplied column was handled.

## Missing And Invalid Values

Blank, NA, N.A., N/A, null and none placeholders represent missing source data.
Native Excel date/time values are staged as JSON-safe source text. Supported
dates include ISO and day-first numeric/month-name formats. An invalid optional
date produces a warning and no fabricated date. Invalid identity/class data or
unusable rows are not admitted; other eligible rows can still be committed.

Exact application identities are checked within the current workspace. Without
an application number, a cautious mark/applicant/classes/jurisdiction/office
combination is required for automatic matching. A mark alone is not unique.
Unauthorized record labels are never disclosed by duplicate suggestions.

## Renewal Alerts And Corrections

The import creates an internal in-app intent for the importer, using the shared
notification queue and current permissions. This is not a verified legal
deadline or a claim of email/provider delivery.

- The alert is scheduled at 09:00 in the configured IP workspace timezone,
  one calendar month before the valid source date.
- Month-end is clamped to the preceding month's last day. March 31 maps to
  February 28 or February 29 in a leap year, not a fixed thirty-day offset.
- If that alert time has passed but renewal is still upcoming, it is due soon
  immediately. Blank, invalid or already-past due dates do not create an alert.
- Portfolio shows the current source renewal date and queue/delivery state.
  Queued means scheduled, not delivered.
- From the committed import row, select **Edit source renewal date**. Review
  the current value, enter a correction reason, change or clear the date,
  then select **Save source date**.
- A correction creates a canonical particular version. Pending old intents are
  cancelled; dispatch also checks current source date/version, recipient
  access and lifecycle. An unchanged date already delivered is not sent again.
- Original import rows remain immutable evidence of the uploaded source.
  They do not silently change to match a later correction. Reloading Portfolio
  shows the corrected current value; clearing removes its current alert.

Email, messaging and external calendar consent/configuration remain separate
provider workflows. This import does not enable them or certify them.

## Court Calendar

1. Open Calendar and select the required month, week or day.
2. Hearings show SC, HC or DC only from stored court configuration. Other
   forums retain their configured identity. Names, district, city and court
   number come from the associated Matter/catalog, never guessed from text.
3. Hearings on one date use the existing catalog display order, then known
   time and stable Matter/event ties. Tasks and other deadlines keep their
   existing relative ordering.
4. In month view, select a date number to inspect all that date's events and
   full identities, including those initially visible in a narrow calendar cell.
5. In month view, select **+N more** to inspect exactly the hidden events for
   that date. The count equals the hidden collection. Links retain the relevant
   Matter or work-area destination.
6. Close the month-view dialog or press Escape; focus returns to its trigger.
   Reopening does not duplicate events or change the current calendar view.

Exact hearing times retain their timezone; session-only timings retain the
stored session, and unpublished time is not replaced with midnight. Missing
bench/district/city values are not invented. Existing Google/Outlook controls
remain separate and preserve their consent and no-paid test boundaries.

## Errors And Historical Reopening

Authentication, authorization, parser, validation, conflict, rate-limit,
transport and server failures must retain their actual category. A preview
is not completed import, and a system failure is not partial success. Retain
the safe request identity when reporting a failure, not a session token.

A historical reopening report requires the reported Matter and its persisted
lifecycle/audit evidence. An explicit authorized Disposed -> Intake action is
not silent resurrection. Generic edits/imports/child workers must not reopen
terminal records. The bounded production sample reviewed for this task does
not establish the cause of every previous reopening report.
