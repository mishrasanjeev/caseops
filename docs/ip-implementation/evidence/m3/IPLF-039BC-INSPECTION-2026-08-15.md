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
3. The features are not uniformly valuable. `UJ-62-EXC-05` (date-only timezone),
   `UJ-57-EXC-01/02` (reassignment without capability or ethical-wall checks) and
   `UJ-51-EXC-07` (privileged correspondence reaching portal or AI) are
   **client-facing correctness and confidentiality risks**. The rest are
   completeness gaps.

## Confidence and limits

- This is **inspection, not verification**. Nothing here was proven by a test,
  and the "implemented" verdicts are candidates for per-path tests, not
  evidence. No manifest status was changed on the strength of this document.
- Verdicts marked *low* confidence (`UJ-51-EXC-05`, `UJ-51-EXC-08`,
  `UJ-57-EXC-06`) need a closer read before being acted on.
- Absence was established by targeted search plus reading the owning service.
  A behaviour implemented somewhere unexpected could have been missed.
