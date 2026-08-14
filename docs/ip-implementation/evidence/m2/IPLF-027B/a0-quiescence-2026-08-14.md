# IPLF-027B A0 rule-governance quiescence - 2026-08-14

## Status and boundary

This artifact records schema-free A0 application and release-control
implementation anchor `f8a3c2c579b5d98c77827a3651cebd6c8a42a12a`, rebased on
canonical predecessor `3177f0176305e8790f40c3f771daebe595087955`. It does not
claim exact-head GitHub checks, merge, deployment, production drain, migration,
activation, or completion of IPLF-027B, RULE-GOV-01..08, UJ-47, UJ-67, or the
IP program. The immutable implementation anchor has repository-local evidence
only; this separate evidence head and all release evidence remain pending.

The existing `CASEOPS_IP_RULE_GOVERNANCE_ENABLED` setting remains `false` by
default. With the flag off, the canonical service rejects each in-scope writer
with HTTP 503 before its first authoritative database read, lock, insert,
update, audit write, or commit. The typed detail is:

```json
{
  "code": "ip_rule_governance_quiesced",
  "reason": "rollout_disabled",
  "rollout_flag": "ip_rule_governance_enabled",
  "detail": "IP rule-governance mutations are temporarily unavailable during the controlled ownership rollout drain."
}
```

Setting the flag to `true` preserves the existing governance service paths.
The five existing legal-deadline mutation paths remain operable with the flag
off. A0 adds no schema, endpoint, worker, scheduler, provider call, legal act,
or external effect.

## Writer inventory

The repository audit found that
`apps/api/src/caseops_api/services/ip_deadline_workflow.py` is the only module
that constructs or updates `IpRuleSet`, `IpRuleVersion`,
`CompanyIpRulePolicy`, or `IpDeadline`.

The A0 fence covers the three public rule-governance writers present on main:

| Writer | Inclusion reason |
|---|---|
| `propose_rule_version` | creates the shared rule set, candidate version, and proposal audit |
| `activate_rule_version` | changes rule status, retires a predecessor, and creates or updates the company policy selection |
| `transition_rule_version` | retires or disables an active/approved rule and records the transition audit |

Each guard is the first executable line in the public service function, so the
fence also applies to future non-HTTP callers of those functions.

The following paths are deliberately excluded:

- `propose_deadline`, `confirm_deadline`, `override_deadline`,
  `recalculate_deadline`, and `complete_deadline` consume an already active,
  immutable rule/company-policy selection but do not change governance
  ownership. Blocking them would prevent ongoing legal operations without
  improving the A0 ownership drain. The full API journey explicitly proves all
  five remain operable with the governance flag false.
- `rule_impact`, `deadline_impact`, `deadline_workspace`, and `/api/ip/readiness`
  remain read-only and available for drain inspection and operator recovery.
- `propose_calendar_version` and `activate_calendar_version` own independent
  working-calendar rows. They do not create or update a rule, company rule
  policy, or rule-bound legal deadline. Calendar-backed deadline calculation
  remains operational because it does not mutate rule-governance ownership.
- Pure calculation in `services/ip_deadlines.py` has no database or legal
  effect.
- IP deadline coverage/reassignment and restricted incident commands retain
  operational continuity and risk-response records, but do not mutate a rule,
  company rule policy, or `IpDeadline`.
- Existing Matter/shared-work deadline services remain their canonical owner.
  The IP shared-work adapter rejects updates to a projection linked to an
  `IpDeadline`; generic operational state never changes authoritative legal
  evidence. A0 therefore does not spread an IP rollout flag into the shared
  Matter domain.
- No standalone company-policy selection endpoint exists on the A0 baseline.
  The planned A1 endpoint must be protected by this fence from its first
  revision; A0 does not introduce it.

## Fresh pre-A0 production baseline

PR #226 merged as exact canonical main
`3177f0176305e8790f40c3f771daebe595087955` after both its repair and
promotion heads passed their complete required checks. Exact-main CI
`31819401226`, Security `31819401221`, and CodeQL `31819401234` also passed.
The normal build/deploy path produced and served this exact predecessor:

| Evidence | Exact identity/result |
|---|---|
| API Cloud Build | `e25baf00-ec0a-4ae2-848b-74e8e56a8f99` - success |
| API immutable image | `sha256:ade0528b789513012960f9ceae2fb915d41306d604512befb0b0641e22b62537` |
| API service | `caseops-api-00293-nf2` - ready, untagged latest, 100% traffic, exact full release SHA |
| Web Cloud Build | `174759dd-aab0-48e2-96c9-eff2b586c9ad` - success |
| Web immutable image | `sha256:d2f08ae2a0786d3489dc7cd70a6072c229b37524a630df6f2c7ee973043dbfbe` |
| Web service | `caseops-web-00271-cgk` - ready, untagged latest, 100% traffic, exact full release SHA |
| Migration | `caseops-migrate-job-6wn7k` - 1/1 success on the exact API image |
| Canonical recurring jobs | all six on the exact API image; five schedulers enabled and authority metadata intentionally paused with timeout 43200 |
| Production workflow | `31819401239` - RAM/IP 69 passed, 3 failed, 4 skipped; Notice 2 passed |

The production failures are only the unchanged recommendation/citation HTTP
503 set caused by exhausted OpenAI credits; bulk import and case tracking pass.
This remains a red global production gate. No provider recovery is inferred,
and the authority-metadata scheduler remains paused.

The serving API predecessor does not contain the A0 fence and has no explicit
governance environment override; its setting only falls back to the existing
default false. It is therefore part of the unfenced writer-capable retirement
cohort after exact A0 is serving. The manually invokable
`caseops-ip-qa-bootstrap` job remains on older unfenced writer-era image digest
`sha256:a240a974dbd8ed12a05b9ee179209dc1d8da3618fed2899bd07e877e84d78b4b`
and must be repinned to exact A0 without execution. Recheck that no
writer-capable execution is running immediately before rollout.

## A0 / A1 / A2 rollout protocol

### A0 - deploy and prove quiescence

1. Before deployment, record the exact writer-capable revision allowlist, zero
   running Cloud Run Job executions, and a read-only fingerprint/max-timestamp
   snapshot for rule sets, rule versions, company policies, and governance
   audits. Validate and merge A0, then deploy that exact revision with
   `CASEOPS_IP_RULE_GOVERNANCE_ENABLED=false` explicitly present on the API
   container. Repin any manually invokable writer-era job image, including
   `caseops-ip-qa-bootstrap`, to the exact A0 digest without executing it.
2. Route 100% of API traffic to exact A0. The canonical deploy script uses
   `--to-latest --clear-tags` and now fails unless observed generation, ready
   conditions, latest-created/latest-ready identity, exact release SHA,
   explicit false governance flag, and the sole untagged 100% spec/status
   traffic entries converge. It also resolves the serving revision and requires
   its immutable API image to match the just-built digest. Independently
   preserve the returned service and revision JSON and prove the immediate
   predecessor is retired with no traffic or tag. Define `T_ROUTE` only on
   that first fully converged read.
3. Before destroying rollback history, run the exact A0 production checks: all
   three governance writers return the typed 503 without a fingerprint change;
   impact/workspace/readiness reads work; all five legal-deadline writers remain
   operable; and the unchanged dated production suite targets the exact serving
   A0 revision.
4. Allow at least 301 seconds of natural drain after both `T_ROUTE` and the old
   revision's retirement observation. This is only a minimum, not termination
   proof. Query old-revision request, stdout/stderr, and error logs from before
   deployment through the drain. For rule-governance POSTs, calculate completion
   as request timestamp plus latency rather than treating request start as
   completion. Re-read the database/audit fingerprint; any unexplained change
   or legacy completion after `T_ROUTE` blocks deletion and A1.
5. Re-enumerate and explicitly delete only the retired, untagged, zero-traffic
   unfenced writer-capable cohort, oldest first and the immediate predecessor
   last. The 2026-08-14 pre-deploy audit found it begins at
   `caseops-api-00258-zv8` (release `d8ac94d`, where these writers first shipped)
   and currently ends at exact predecessor `caseops-api-00293-nf2`. The audited
   36-revision allowlist is:

   ```text
   caseops-api-00258-zv8  caseops-api-00259-kpk
   caseops-api-00260-j75  caseops-api-00261-xnb
   caseops-api-00262-8p5  caseops-api-00263-zl4
   caseops-api-00264-jmx  caseops-api-00265-7zt
   caseops-api-00266-lcq  caseops-api-00267-swr
   caseops-api-00268-6p9  caseops-api-00269-d5g
   caseops-api-00270-5zs  caseops-api-00271-cg8
   caseops-api-00272-2cs  caseops-api-00273-v99
   caseops-api-00274-phv  caseops-api-00275-f7n
   caseops-api-00276-zq8  caseops-api-00277-2ws
   caseops-api-00278-4rq  caseops-api-00279-6pg
   caseops-api-00280-qpf  caseops-api-00281-9bt
   caseops-api-00282-j82  caseops-api-00283-k2x
   caseops-api-00284-jzh  caseops-api-00285-skg
   caseops-api-00286-8x7  caseops-api-00287-ml7
   caseops-api-00288-ccf  caseops-api-00289-l9g
   caseops-api-00290-plb  caseops-api-00291-62b
   caseops-api-00292-sr5  caseops-api-00293-nf2
   ```

   Revisions 00258 through 00292 are currently retired; 00293 is the active
   3177 predecessor and becomes eligible only after exact A0 is ready at 100%
   and the full drain preconditions pass. Include any later unfenced predecessor
   introduced before A0, and recheck every exact target both immediately before
   deployment and immediately before deletion. Preserve all pre-00258 revisions
   and never use a wildcard.
6. Prove deletion completion three ways: each exact target `describe` returns
   genuine `NOT_FOUND`, a fresh revision list has an empty intersection with
   the allowlist, and Admin Activity has one successful revision-delete event
   per target. Revalidate that exact A0 remains latest, untagged, ready, and at
   100% traffic. Define `T_FENCE` only after the final target is absent.
7. Capture the database/audit fingerprint at `T_FENCE`, wait a second window of
   at least 301 seconds plus logging-ingestion slack, and capture it again. The
   fingerprints and governance maxima must be identical; no legacy revision
   completion/error log or writer-capable job may appear after `T_FENCE`.
   Keep the flag off and do not begin A1 if any identity, termination, log,
   database, audit, or job proof is incomplete.

A Cloud Run request timeout is not a liveness or process-termination boundary:
the client can receive a 504 while the container continues working. The
protocol therefore uses explicit writer-capable legacy-revision termination
and observed completion, not a timeout-derived wait. See the official Cloud
Run guidance on
[request timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout)
and [traffic migration and revision tags](https://cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration).

### A1 - expand while every writer remains off

Deploy the additive ownership migration and compatibility code only after A0
drain proof. Keep the flag false throughout migration, backfill, reconciliation,
mixed-revision validation, and rollback rehearsal. A1 owns nullable tenant
ownership, dual-read/dual-write compatibility, ambiguity detection, locking and
concurrency changes, and the new explicit company-policy selection endpoint.
That endpoint must call the A0 fence before its first authoritative read or
mutation.

The A0 boolean fence is sufficient only while the rollout flag stays false.
Before A2, A1 must replace or extend it with server-side enforcement of all
three independent runtime gates: the boolean rollout flag, its configured
rollout expiry, and the current company's `ip_rule_governance` entitlement.
Route-level capability enforcement remains required but is not a substitute
for tenant entitlement or expiry enforcement. The A1 policy-selection command
must be born behind this complete server-side decision. Negative service/API
tests must prove that a flag-enabled but unentitled company and a flag-enabled
but expired rollout both fail before governance read/mutation/audit access.

A1 must also close the known legal-rule defects before any enablement:

- `reviewer_membership_id` must resolve to a distinct active same-company
  membership that actually holds `ip:rules_activate`; custom-role negative
  service and API tests are required.
- Form and fee fixtures cannot be treated as evaluated by comparing two
  caller-supplied strings. Activation of every unsupported rule kind must fail
  closed until a dedicated server evaluator and legal fixtures exist; retaining
  deadline-only activation is an acceptable safe boundary.
- Real PostgreSQL tests and a pre-traffic ownership audit must prove zero NULL,
  missing, mixed, or cross-company ownership/policy/deadline rows and exercise
  proposal, overlapping activation, policy CAS, disable/selection races, and
  the chosen lock protocol.
- Effective-range overlap must fail closed under real concurrency. Emergency
  disable must stop new calculation and auto-confirm, mark or surface every
  dependent candidate, create bounded alerts for every affected company, and
  preserve immutable history; PostgreSQL, API, audit, and alert-delivery tests
  must prove the complete behavior rather than only the status transition.

A1 is not implemented or verified by this artifact.

### A2 - config-only controlled resume

Only after exact A1 CI, migration, reconciliation, revision, database, audit,
production evidence, reviewer-capability and evaluator fail-closed gates,
PostgreSQL ownership/effective-range concurrency proofs, complete emergency-
disable behavior, and the unentitled/expired negative gates pass may an
authorized operator create a config-only revision with the
same validated image and set `CASEOPS_IP_RULE_GOVERNANCE_ENABLED=true`.
Recheck image/config identity and
run the dated governance/deadline acceptance suite. The immediate rollback is
the exact A1 image/configuration with the flag false. Never route to a pre-A0
or other pre-fence image, and do not downgrade the additive ownership schema
after A1 migration/backfill or legal state exists. Later constraint contraction
requires its own observation window and evidence; it is not part of A0, A1, or
this artifact. A2 is forbidden if any runtime, reviewer, evaluator,
effective-range/emergency-disable, PostgreSQL-ownership/concurrency,
negative-test, or exact deployed evidence gate is missing.

## Local verification

The candidate currently has repository-local evidence only:

| Command | Result |
|---|---|
| `uv --directory apps/api run pytest -q tests/test_ip_rule_governance_quiescence.py` | 9 passed |
| `uv --directory apps/api run pytest -q tests/test_ip_deadline_workflow.py` | 9 passed; governance setup/transition use explicit true, while all five legal-deadline writers are exercised after switching false |
| combined focused tests | 18 passed; zero skipped |
| `uv --directory apps/api run pytest -q tests/test_deploy_prod_hardening.py` | 19 passed; includes exact traffic/config/image success and fail-closed traffic, generation, flag, and immutable-image drift |
| combined A0 service/workflow/deploy-hardening suite | 37 passed; zero skipped |
| `uv --directory apps/api run pytest -q tests/test_ip_data_governance_map.py` | 10 passed; exact 028C projection/control regression retained after rebase |
| focused Ruff | passed |
| `uv --directory apps/api run ruff format --check src/caseops_api/services/ip_deadline_workflow.py tests/test_ip_rule_governance_quiescence.py tests/test_ip_deadline_workflow.py tests/test_deploy_prod_hardening.py` | 4 A0-changed Python files already formatted |
| `bash -n scripts/deploy-prod.sh` | passed with Git for Windows Bash |
| program, ownership, ARCH-OPS, data-class, data-governance registry/map, change-gate, and M2 ownership validators | passed |

The focused fence tests use a session sentinel that fails on any database
access. They cover all three governance writers, the exact typed 503, false ->
true -> false settings-cache order, independent calendar mutation, and
accessible read-only impact/workspace paths. The existing end-to-end API/service
tests set up rule governance with the flag true, switch it off, and then prove
deadline proposal, confirmation, recalculation, override, and completion plus
their audit/projection behavior remain operable. The separate exception test
retains transition and tenant-isolation coverage with governance enabled.

## Remaining release gate

A0 has exact implementation anchor `f8a3c2c579b5d98c77827a3651cebd6c8a42a12a`
but remains unreleased until the evidence head passes independent review and
complete exact-head CI/Security/CodeQL, canonical merge, exact image/revision
deployment, 100% traffic identity,
legacy-route removal, explicit writer-capable legacy-revision termination,
observed shutdown,
revision-log plus rule/version/policy/audit no-write proof, and the same dated
production acceptance against the exact serving revision. The flag must remain
false through A1 and A2 must remain forbidden until every runtime,
entitlement/expiry, qualified-reviewer, unsupported-kind evaluator,
effective-range/emergency-disable, strict PostgreSQL ownership/concurrency,
negative-test, and exact-deployed gate is verified. No local green test is
deployed evidence.
