# Historical Secret-Scan Review: 1 November 2026

Ownership: existing J08/M08 and J14/M14 security/release gates. Candidate only;
full Docker, hosted gates, protected main and exact-serving acceptance pending.
Native application code, tooling and MacBook acceptance are outside this change.

## Observed Failure And Root Cause

Scheduled Security41301909540 ran against main02d0b0e4. Its immutable tracked
tree completed clean after26 existing provenance translations. The all-refs
history selected3206commits and reported58findings:31 matched already-reviewed
origins and27 did not. Failure reason was History has unreviewed findings;
both scanner containers were cleaned. This is not a timeout or dependency audit.

The27 instances resolve to14 distinct original source spans in newer unmerged
test commits. A green release-time tree/PR-range scan does not certify a later
scheduled all-refs snapshot. Its failure also does not prove a secret in the
serving application. Each boundary and its selected DAG must be reconciled.

## Independent Source Review

The companion JSON pins each exact origin fingerprint, complete Git-blob
SHA256, original one-line span SHA256 and non-credential classification.
All14 original byte spans match the retained report; no value was inferred
from the generic-api-key rule name. Source context and actual argument use:

| Classification | Origins | Non-Secret Use |
| --- | ---: | --- |
| Calendar fixture key | 1 | A deterministic LegalWorkingCalendar key identifies a stored local test precondition, not authentication. |
| Calendar fixture call | 2 | activeCalendar receives a public test registry label after a runtime API client argument. The argument is a calendar key/name. |
| Idempotency fixture key | 6 | Synthetic journal-ingestion replay identities, including a database equality assertion. These identify commands, not authorization. |
| Matter fixture code | 4 | Deterministic Matter codes passed after independently created token arguments to local test helpers. The flagged literal is the Matter code, not the token variable. |
| Calendar policy fixture key | 1 | The workspace test payload identifies a public holiday-calendar key beside its timezone and weekday policy. |

The scan's27 instances include merge and shifted-line copies. The correction
adds only14 origin:path:rule:line fingerprints to the existing reviewed policy.
Current-path exceptions, test-folder exclusions, content/value patterns,
rule-wide allowances, branch exclusion and history rewriting are forbidden.
Existing provenance still requires the complete unchanged span, exact blame
origin/path and current selected history. A new origin or changed suffix/value
remains blocking. No scanner runtime or scan-boundary change is needed.

## Regression And Release Boundary

The existing Security workflow also accepts an explicit manual dispatch.
That event selects the same complete all-refs boundary as the daily schedule;
checkoutHEAD and full-clone fences remain mandatory. It runs the unchanged
eight-job security inventory, native regressions and redacted scanner receipts.
The actual GitHub trigger remains workflow_dispatch in its retained run data,
not a fabricated scheduled run. New negative canaries prove that manual replay
still rejects an unmerged secret and a mismatched candidate. This permits
candidate verification immediately after a repair without broadening access,
relaxing timeouts, excluding refs or waiting for the next daily schedule.

The standard test_secret_scan_gate.py inventory binds all14 policy entries to
the hash ledger and constrained fixture uses. Selected reachable origins are
checked against immutable bytes; unselected origins are counted separately and
never described as reverified. Missing selected blobs remain blocking.

New native scanner cases prove a clean main still rejects a secret on an
unmerged ref, while only an explicitly reviewed exact origin can pass there.
Existing positive canaries and changed/reintroduced origin rejection cases
remain unchanged. Retain an actual nonempty all-refs scan in addition to hosted
PR-range evidence. No empty report, timeout, filtered history or skipped case
can close the gap. The first new binding run also exposed a test-helper
subTest exception-capture defect; its failed evidence is retained separately.
The corrected red run fails only because the14-entry policy section is absent.

Use low-entropy, clearly named public fixture labels in new tests and avoid
placing them inline after token arguments when the helper signature permits
a named local code variable. Never rename a real credential to evade scanning.
Immutable historical false positives still require explicit source review.

Both original Excel summaries must receive final actual release/test/skip
results only after the requested complete Docker and production gates finish.
Their existing37fixed/6partial/1inconclusive counts are not blanket closure of
external legal-review, consent, MFA or retained calendar-cleanup dependencies.
