# IPLF-028A policy and hold authorization - 2026-08-20

## Verdict

**GO with caveat.** Four changes completing the records-governance policy and
hold authorization lane are merged, deployed, and independently identified on
exact production revision `9e458efd43cd8db8450bd7de96ff46a941744edc`. Commit
identity is proven on both serving surfaces, every migration in the window is
confirmed applied from the migrate-job's own logs, and the governed operation
boundary is unchanged: nothing here executes an export, purge, offboarding,
restore, retention decision, or any other real legal or data act.

A clean `GO` is **not** available and is not claimed. Two caveats are structural
and stated in full under *What remains unproven*: no route in this repository
called the records-governance services at the time this evidence was captured,
so every refusal tier is proven by tests and by construction rather than by
live traffic; and no database-plus-object restore rehearsal has been performed,
so backup **recoverability** remains unproven while backup **configuration**
exists.

`IPLF-028A` remains `in_progress / not_run / blocked`. This document records what
was verified, not slice completion.

## What changed in this window

| PR | Merge commit | Subject |
| --- | --- | --- |
| [#267](https://github.com/mishrasanjeev/caseops/pull/267) | `3bb0237be3cd431ade4ea9e666c78b9c94a4041b` | Tenant data-operation approval workflow (DATA-GOV-05) |
| [#269](https://github.com/mishrasanjeev/caseops/pull/269) | `4db36224b866697365b7b0da13a8d2ade675b9c9` | Close two fail-open defects found by adversarial review |
| [#270](https://github.com/mishrasanjeev/caseops/pull/270) | `3d6e36faaf98af66f626ce15384ddfd8ede4cbe4` | Compile the reviewed data-class registries into the runtime |
| [#273](https://github.com/mishrasanjeev/caseops/pull/273) | `9e458efd43cd8db8450bd7de96ff46a941744edc` | Make a retention schedule authorize, and require that it did (DATA-GOV-02) |

### Blocker movement

`IPLF-028A-RUNTIME-DATA-CLASS-REGISTRY` is **closed** by #270. Admission is no
longer a six-name frozenset duplicated from the reviewed registry; it is a
compiled projection rendered from the reviewed artifacts and gated in CI by
`scripts/ip_data_class_projection.py validate`. The reviewed YAML cannot be read
at runtime at all - `apps/api/Dockerfile` copies `src` and `alembic` and not
`docs/` - which is why the projection is compiled into the shipped package
rather than loaded from disk.

`IPLF-028A-RES-13-REHEARSAL` is **owner-waived**, not resolved. See
`docs/ip-implementation/OWNER_WAIVER_RES13_RESTORE_REHEARSAL_2026-08-19.md`. The
rehearsal was not performed, deferred, or partially completed.

`IPLF-028A-POLICY-AND-HOLD-AUTHORIZATION` is **partially addressed**. Of the four
artefacts it names:

| Artefact | State |
| --- | --- |
| Legal-hold activation/release workflow | Implemented (DATA-GOV-05) |
| Step-up / four-eyes decision | Implemented (#267) |
| Approved retention schedule | **Mechanism** implemented (#273); **content** not supplied |
| Tenant-facing review contract | Not implemented |

The retention schedule's content - which classes are kept, for how long, on what
legal basis - is a decision for the firm's lawyers. Inventing defaults would
manufacture exactly the approval this blocker says is missing. While no schedule
is approved, a retention purge cannot be authorized at all; that is the honest
consequence of having no schedule, not a regression.

## Exact repository gates

| Control | Exact result |
| --- | --- |
| #267 exact-head CI | `32264004714` success (head `59e44ef1d277816221914474b84bb39f9785a63d`) |
| #269 exact-head CI | `32277354014` success (head `aae8348dcd1041e14dd0e936ece3fcc2a6ee67ff`) |
| #270 exact-head CI | `32319726830` success (head `e4e061268c52006a20ce8d0f67667432d57fcc8a`) |
| #273 exact-head CI | `32361095426` success (head `7c1e6a99e45ab3b218f56929a990890fbe0675d8`) |
| Governance-scoped suite | `305 passed, 3 skipped, 3075 deselected` on `ec62ff6f` |
| `ip_data_class_projection validate` | valid |
| `ip_data_governance_registry validate` | valid: six dry-run-only data classes |
| `ip_data_governance_map validate` | valid |
| `ip_program_manifest validate` | valid: 436 requirements, 50 families, 68 journeys, 317 atomic paths |
| `ip_m2_ownership_audit validate` | valid: 26 M2 slices |

Command for the suite row, run from the repository root:

```
scripts/verify-backend.sh -k "datagov or data_governance or data_class or \
  integrity or retention or governance or repo_paths or approval"
```

## Exact production deployment and independent verification

| Control | Exact result |
| --- | --- |
| Deployed commit | `9e458efd43cd8db8450bd7de96ff46a941744edc` |
| API surface | `https://api.caseops.ai/api/build` -> `release_sha 9e458efd…744edc`, revision `caseops-api-00311-grq` |
| Web surface | `https://caseops.ai/api/release-identity` -> `release_sha 9e458efd…744edc`, revision `caseops-web-00289-9r2` |
| Canonical verifier | `scripts/verify_deployed_release.py --expected-sha 9e458efd43cd8db8450bd7de96ff46a941744edc` returned both revisions and the matching SHA |
| Health | `{"status":"ok"}` |
| Rule governance | explicitly `false` |

Commit identity is therefore proven on both serving surfaces rather than
inferred from the deploy script's exit code.

### Migrations applied in this window

Confirmed from the migrate-job execution logs, not from step success:

| Revision | Confirmed by |
| --- | --- |
| `20260819_0001` | `caseops-migrate-job-fvstp`: `Running upgrade 20260818_0001 -> 20260819_0001` |
| `20260820_0001` | `caseops-migrate-job-fvstp`: `Running upgrade 20260819_0001 -> 20260820_0001` |
| `20260820_0002` | `caseops-migrate-job-8rhgs`: `Running upgrade 20260820_0001 -> 20260820_0002` |

## Defects found and closed in this window

Every one is the same shape - a control that reports success when it could not
verify anything, or a guard that cannot fire - and four were in code shipped
earlier in the same lane.

| Defect | Where | Closed by |
| --- | --- | --- |
| `purge_dependency_plan` dropped unknown classes silently while reporting `order_is_complete: true` | `services/data_governance.py` | #269 |
| `governance_integrity_scan` resolved its map path with `parents[5]`, raising `IndexError` at import in the container - above the `try/except` written to report "unavailable" | `services/governance_integrity_scan.py` | #269 |
| Dry run accepted any retention policy version that existed, never checking status; a `candidate` authorized an operation | `services/data_governance.py` | #273 |
| A proposal could carry its own approval evidence via an unfiltered `**terms` splat | `services/retention_authorization.py` | #273 |
| A whitespace-only string counted as naming an indefinite-retention approval | `services/retention_authorization.py` | #273 |
| Two active retention versions were resolved by `session.scalar` picking one arbitrarily | `services/retention_authorization.py` | #273 |

A test asserting the first defect's behaviour as correct
(`test_an_unknown_data_class_is_ignored_rather_than_invented`) was inverted
rather than deleted, because a test that blesses a fail-open is worse than no
test.

Two guards were **removed** rather than kept, on the grounds that a check which
cannot fire invites the next reader to trust it: an identity re-check in
`activate_version` made dead by `trg_data_retention_versions_immutable`, and an
early return in the projection gate that made every assertion below it
unreachable.

## What remains unproven

State these before quoting any part of the verdict above.

1. **No route exercised these services at capture time.** `create_dry_run_manifest`
   and `run_integrity_scan` had no caller outside `apps/api/tests/`. Every 503
   and 409 refusal tier is proven by tests and by construction, never by a
   request against the deployed build. Data-governance routes were subsequently
   merged under the IPLF-028B lane (#274, #275, #277) and are **not** covered by
   this evidence.
2. **Backup recoverability is unproven.** No database-plus-object
   application-cutover restore rehearsal has been performed. Point-in-time
   recovery is disabled on `caseops-db`, giving a real RPO near 24 hours against
   RES-01's 15-minute target. No RTO is evidenced. Backup *configuration* exists;
   backup *recoverability* does not.
3. **No approved retention schedule exists.** DATA-GOV-02 has a mechanism and no
   content. Retention purges are unauthorizable until a schedule is approved.
4. **No tenant-facing review contract exists.**
5. **11 of 271 inventoried data classes carry a reviewed classification.** The
   remaining 260 are published as a count by the `data_class_review_coverage`
   integrity check rather than omitted, and that check cannot read `ok` while
   any class is unreviewed.
6. **No named human acceptance is claimed or implied.** No lawyer, security
   reviewer, privacy owner, SRE, or pilot customer has reviewed this work.

## Reversal

Nothing in this window seeds data or enables an execution path. The four merges
are additive; the three migrations are additive and each carries a downgrade
that refuses rather than discards recorded evidence.
