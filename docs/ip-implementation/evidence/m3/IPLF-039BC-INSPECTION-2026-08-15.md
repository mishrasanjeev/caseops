# Code-inspection audit: IPLF-039B and IPLF-039C

**Date:** 2026-08-15
**Method:** read the implementing services and schemas and decide, per path,
whether the behaviour exists. **No tests were written and none were run**, so
every judgement below is inspection-grade and marked with its confidence.
**Purpose:** find out how many of these 38 paths need *features* rather than
tests, before committing effort to writing 38 per-path tests.

## Why this audit exists

Three IPLF-039 slices audited by writing tests each found the recorded
`deployment_verified` status running ahead of what was built: `039A`
auto-approves filing manifests with no reviewer, `039D` had four unbuilt paths
of six, `039F` had four unbuilt of seven plus one the code contradicts. Writing
tests for behaviour that does not exist is impossible, not merely slow, so the
remaining two slices were inspected first.

## IPLF-039B — 16 paths, roughly 9 implemented

The strongest of the IPLF-039 family. `discover_ip_evidence_candidates` spans
`CompanyNotice`, `Communication`, `MatterAttachment` and Drive candidates,
assigns each a **fingerprint** (`sha256_hex` where available, otherwise a
derived canonical hash), and marks a repeat as `status="duplicate"` with
`duplicate_of_candidate_id`. `link_kind` distinguishes `official_notice`,
`correspondence` and `instruction`. Candidates default to `needs_review` and
`review_ip_evidence_candidate` fences on `expected_status`.

| Path | Verdict | Basis |
|---|---|---|
| `UJ-51-NORMAL` | **implemented** (high) | discovery + typed `link_kind` + notice link |
| `UJ-51-EXC-01` | **implemented** (high) | fingerprint dedup sets `duplicate` + `duplicate_of_candidate_id` |
| `UJ-51-EXC-02` | **implemented** (high) | `add_ip_notice_link` references an existing `CompanyNotice`; no copy |
| `UJ-51-EXC-03` | **absent** (medium) | no immutability guard found protecting held evidence from a convenience-file replacement |
| `UJ-51-EXC-04` | **implemented as absence** (high) | costs exist only via explicit `add_ip_cost_item`; no notice field creates one |
| `UJ-51-EXC-05` | **uncertain** (low) | `Communication` has a `BOUNCED` status, but discovery does not appear to exclude bounced messages from `link_kind="instruction"` |
| `UJ-51-EXC-06` | **implemented** (high) | candidates default to `needs_review`; ambiguity stays pending |
| `UJ-51-EXC-07` | **absent** (medium) | document privilege policy exists for `IpDocument`, but no equivalent gate on discovered correspondence |
| `UJ-51-EXC-08` | **uncertain** (low) | discovery is gated by `_docket_or_404`, which fails closed at docket level; mixed-access notice semantics not modelled |
| `UJ-55-NORMAL` | **implemented** (high) | discovery + review workflow |
| `UJ-55-EXC-01` | **implemented** (high) | unmatched candidates remain `needs_review` |
| `UJ-55-EXC-02` | **implemented** (medium) | `_docket_or_404` returns 404, so no name or count leaks |
| `UJ-55-EXC-03` | **absent** (medium) | no notice-audience model to infer or refuse to infer |
| `UJ-55-EXC-04` | **absent** (high) | no malformed or encrypted attachment handling in the IP path |
| `UJ-55-EXC-05` | **implemented** (medium) | fingerprint dedup covers webhook/poll duplication of the same message |
| `UJ-55-EXC-06` | **partial** (medium) | candidates persist independently of the source row, but no legal hold participates |

**~9 of 16 implemented, ~7 needing work.**

## IPLF-039C — 22 paths, roughly 4 implemented

The thinnest slice in the family, as predicted. `ip_docket_control_report`
returns six counts plus cost totals. Reassignment guards only that the
replacement differs and the source membership exists. Calendar projection
creates `CalendarEventSync` rows in `PENDING` when a connected calendar exists.

There is **no** sign-off, export, escalation, backup-policy, stale-provider,
capability-check, ethical-wall, preview-token, expiry, redaction or timezone
rule anywhere in this path. Targeted searches for `sign_off`, `export`,
`escalat`, `backup_policy`, `stale`, `revoked`, `outage`, `rate_limit` and
`redact` in `ip_operations.py` returned nothing.

| Journey | Paths | Verdict |
|---|---|---|
| `UJ-50` daily docket | 5 | `NORMAL` **partial** — counts exist, no saved team queues or capacity indicators. `EXC-01` **implemented** (medium) — the report is built from the access-filtered listing. `EXC-02`, `EXC-03`, `EXC-04` **absent** — no backup policy, no stale-provider concept, no re-escalation. |
| `UJ-57` reassignment | 7 | `NORMAL` **implemented** (high). `EXC-01` … `EXC-05` **absent** — no capability check, no ethical wall, no assignee rejection, no preview token for concurrent change, no temporary emergency coverage with expiry. `EXC-06` **uncertain** — label snapshots exist on some rows but original-actor attribution after reassignment is unverified. |
| `UJ-59` control report | 4 | `NORMAL` **partial** — the report generates, but there is **no sign-off step at all**, so "produce **and sign off**" cannot hold. `EXC-01`, `EXC-03` **absent** — no incompleteness gate, no export. `EXC-02` **partial**. |
| `UJ-62` external calendar | 6 | `NORMAL` **partial** — a `PENDING` projection row is created. `EXC-01` … `EXC-05` **absent** — no outage or rate-limit retry, no revocation handling, no external-edit reconciliation, no ethical-wall redaction, and **no date-only timezone rule**. |

**~4 of 22 implemented, ~18 needing work.**

`UJ-62-EXC-05` deserves separate mention: *"timezone shift does not move a
date-only legal obligation"* is a correctness rule protecting filing dates from
DST and offset changes. Nothing implements it, and a projection that shifts a
date-only legal deadline across a day boundary would be a real client-facing
defect.

## Totals

| | Paths | Implemented | Needing work |
|---|---|---|---|
| `IPLF-039B` | 16 | ~9 | ~7 |
| `IPLF-039C` | 22 | ~4 | ~18 |
| **Combined** | **38** | **~13** | **~25** |

Across all six IPLF-039 slices the ratio is roughly **30 of 62 paths
implemented**. The remaining work is therefore **not 45 tests** — it is closer
to **30 missing features plus tests for all of them**.

## What this changes

1. **Do not schedule "write the remaining 45 tests."** Roughly half cannot be
   written because the behaviour does not exist.
2. `IPLF-039C` should be treated as **largely unbuilt**, not as a verified
   deployed slice. Its recorded status is the least accurate in the program.
3. The features are not uniformly valuable. Three were called out as
   client-facing risks. **See the correction below: only one was live.**

## Correction — 2026-08-15, after verification

This document originally described three client-facing risks. Verifying each
before fixing it established that **only one was actually exploitable**. The
other two were overstated here and are corrected:

| Risk | Original claim | Verified reality |
|---|---|---|
| `UJ-57-EXC-01/02` reassignment without access checks | client-facing risk | **Confirmed and live.** Bulk reassignment swept coverage across every docket in the company with no access check, so a restricted record or ethical wall could be bypassed by making a walled-off member responsible for its deadline. **Fixed** — both single and bulk reassignment now evaluate the canonical `can_access_ip_docket` policy as the *replacement* and fail closed for the whole batch. |
| `UJ-62-EXC-05` date-only timezone shift | "a filing-date correctness bug waiting for a DST change" | **Overstated — latent, not active.** `CalendarEventSync` stores only `(connection, source_type, source_id, status)` with no start, end, all-day or timezone column. No datetime is projected, so no date can shift. |
| `UJ-51-EXC-07` privileged correspondence reaching portal or AI | "no gate against portal or AI exposure" | **Overstated — latent, not active.** True that no privilege field exists on `Communication`, `CompanyNotice` or `IpEvidenceCandidate`; false that there is live exposure. `IpEvidenceCandidate` is referenced only by `ip_operations.py` and `models.py` — no route, portal surface or AI retriever reads it. |

Both latent gaps are now **pinned by tests** in
`apps/api/tests/test_ip_latent_exposure_guards.py`. If someone adds a portal or
AI surface over correspondence, or a calendar projection carrying real times,
those tests fail and point at the requirement rather than letting the gap ship
silently.

The lesson for the rest of this audit: an "absent" verdict says a behaviour is
unimplemented; it does **not** by itself establish that the absence is currently
exploitable. Exposure has to be traced separately, and I did not do that before
calling all three client-facing.

## Second correction — UJ-62 was under-assessed

Building increment 4 established that **UJ-62 is roughly 5 of 6 implemented, not
1 of 6 partial** as this document originally recorded.

The error was method, not judgement: the search was scoped to
`ip_operations.py`, where `CalendarEventSync` is indeed created as a bare
pointer. The projection work lives in the shared `calendar_sync.py` owner that
the IP path delegates to, and it was never read.

| Path | Originally recorded | Verified |
|---|---|---|
| `UJ-62-NORMAL` | partial, "a PENDING projection row" | **implemented** — `UniqueConstraint(connection, source_type, source_id)` makes resync idempotent, `provider_event_id` retains the stable external id, and the row points at its source rather than copying the legal date |
| `UJ-62-EXC-01` | absent, "no outage or rate-limit retry" | **implemented** — `attempts`, `max_attempts`, `next_attempt_at`, `dead_letter_reason` and `retry_scheduled`/`failed`/`dead_letter` statuses |
| `UJ-62-EXC-02` | absent, "no revocation handling" | **implemented** — `revoke_connection` sets `CalendarConnectionStatus.REVOKED` and audits it; sync rows are not deleted, so history survives |
| `UJ-62-EXC-03` | absent | **absent, confirmed** — no drift detection for an externally edited or deleted event |
| `UJ-62-EXC-04` | absent, "no ethical-wall redaction" | **implemented, and more strongly than required** — `_ip_source_payload` is content-free by construction: the title is `"CaseOps IP - {category}"` and never the docket title, identifier, forum or notes |
| `UJ-62-EXC-05` | absent, "no date-only rule" | **implemented** — `occurs_on` is a `date`; Google receives `{"date": ...}` with no timezone, Outlook `isAllDay: true` over a one-day span |

This is the **second** severity misjudgement in this audit, and both share a
cause: I assessed a behaviour by reading the IP module without tracing to the
shared owner it delegates to. The earlier correction concerned exposure; this
one concerns implementation. An audit of a delegating module must follow the
delegation before it concludes anything is absent.

## Confidence and limits

- This is **inspection, not verification**. Nothing here was proven by a test,
  and the "implemented" verdicts are candidates for per-path tests, not
  evidence. No manifest status was changed on the strength of this document.
- Verdicts marked *low* confidence (`UJ-51-EXC-05`, `UJ-51-EXC-08`,
  `UJ-57-EXC-06`) need a closer read before being acted on.
- Absence was established by targeted search plus reading the owning service.
  A behaviour implemented somewhere unexpected could have been missed.
