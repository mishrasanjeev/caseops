# IPLF-028B route handoff verification - 2026-08-20

## Why this exists

`evidence/m2/IPLF-028A/policy-authorization-2026-08-20.md` records its first and
largest caveat as:

> No route called the records-governance services when this was captured.
> `create_dry_run_manifest` and `run_integrity_scan` had no caller outside
> `apps/api/tests/`. Every 503 and 409 refusal tier is proven by tests and by
> construction, never by a request against the deployed build.

Routes have since been merged under the IPLF-028B lane (#274, #275, #277). This
document is the verification of whether those routes actually surface the
IPLF-028A refusal tiers - the question that caveat asks - and therefore whether
it can be retired.

The routes are the Codex half of IPLF-028B and were not modified to produce this
evidence. No test was added to them. Every result below comes from a throwaway
probe against the merged surface at `ec62ff6f18ce084beb49bd8bf97b51893fdd2288`.

## Result

**The refusal tiers survive the route boundary.** Nine of ten probes behave
correctly. One gap is real, is not in the routes, and has a fix already open.

| Probe | Status | Behaviour |
| --- | --- | --- |
| Dry run, reviewed class | `201` | Manifest persisted; items non-executable |
| Dry run, inventoried but unreviewed (`matters`) | `409` | "inventoried by the repository-wide data map but no reviewed governance classification exists" |
| Dry run, governed by another slice (`domain_outbox_events`) | `409` | Names IPLF-027A as the governing slice |
| Dry run, unknown class | `409` | Original `data_class_not_registered_for_dry_run` message preserved |
| Dry run, retention version not found | `404` | Refused before any manifest work |
| Execute | `503` | Typed refusal: "stores dry-run evidence only" |
| Integrity scan, healthy projection | `200` | `data_class_review_coverage` reports `findings`: 11 of 271 reviewed |
| Legal-hold summary | `200` | - |
| Dry run, **stale projection** | `503` | Whole request refused: "rendered from a different ORM schema than this build carries" |
| Integrity scan, **stale projection** | `200` | Per-check degradation, see below |

### The stale-projection integrity case, examined

A `200` here initially looked like a fail-open and is not one. Under a stale
projection the endpoint still answers, but the checks inside it degrade
correctly:

| Check | Healthy | Stale |
| --- | --- | --- |
| `data_class_review_coverage` | `findings` - 11 of 271 reviewed | `unavailable`, `blocked_by: data-class-projection` |
| `held_at_risk` | `ok` | `unavailable`, `blocked_by: data-class-projection` |

`TenantDataGovernanceIntegrityReport` exposes `unavailable_count` and
`is_complete`, so a client cannot read "no findings" as "healthy" while checks
did not run. Reporting per-check status rather than refusing the whole scan is
the correct design for a scan endpoint: refusing wholesale would hide the checks
that *could* still run.

## The one real gap

**Every refusal arrived with the same machine-readable type.** All three
distinct 409s carried `https://httpstatuses.com/409`:

```
unreviewed             409  https://httpstatuses.com/409
governed elsewhere     409  https://httpstatuses.com/409
unknown                409  https://httpstatuses.com/409
```

Three refusals with three different remedies - review that class, use the slice
that admits it, fix the request - are indistinguishable to a machine. The
human-readable `detail` differs and is correct; only the switchable identifier
is lost.

This is not a defect in the routes. The RFC 7807 handler listed `type` among its
reserved problem members, so the slug every service already raises was discarded
before rendering. It affects 22 slugs repository-wide.
[PR #279](https://github.com/mishrasanjeev/caseops/pull/279) fixes it, and
applying that branch on top of `ec62ff6f` and re-probing the same three routes
gives:

```
unreviewed             409  data_class_registered_but_not_reviewed
governed elsewhere     409  data_class_reviewed_by_other_slice_not_admitted
unknown                409  data_class_not_registered_for_dry_run
```

## Effect on the IPLF-028A caveat

The caveat is **retired in its structural form and narrowed to one condition**.

Retired: the refusal tiers are no longer proven only by construction. They are
now exercised through authenticated, capability-gated HTTP requests against the
merged surface, and the projection guard - the control most likely to fail
silently - refuses the whole dry run rather than answering from a projection
that does not describe the build.

Not yet retired: the machine-readable half. Until #279 merges, a client can see
*that* it was refused but not *which* refusal it was, so any downstream workflow
switching on the refusal type is unproven. State this alongside any claim that
the tiers are verified.

Unchanged by this document: the second IPLF-028A caveat. No restore rehearsal
exists, PITR remains disabled on `caseops-db`, and backup recoverability is
still unproven.

## Boundary note

Produced entirely by observation. No route, schema, generated client, or UI file
in IPLF-028B was edited, and no API test was added to it. The probe was a
throwaway not committed to the repository. Codex owns the slice's status, test,
and evidence references under the reconciled single-owner execution policy.
