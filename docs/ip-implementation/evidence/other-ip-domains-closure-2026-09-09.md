# Other IP Domains: September 09 Implementation Evidence

## September 10 Resume

Historical report retained below without rewriting its failed or passed evidence.
See [the September 10 checkpoint](other-ip-resume-2026-09-10/README.md) and its
exact owned-file manifest for the current eight-table DES/COPY/LIC workflow code,
versioned `.2` contracts, 64-test backend and 13-test UI results, and open scope.
The three-table inventory, single contract-version request and larger Docker
limits below are historical, not current integration/test instructions.
All four slices remain partial; the other seven domains remain unfinished.

Status: Partially implemented. Full-domain activation/closure: NO-GO. No commit, push, deployment or
production mutation is authorized or performed by this track.

## Ownership And Snapshot

Owns IPLF-090A/B and IPLF-091A/B only. Independent worktree:
`C:/Projects/CaseOps/caseops/.worktrees/codex-other-ip-domains-closure-20260909`.
Branch: `codex/other-ip-domains-closure-20260909`.
Baseline: `5145fb3a4b51b26af116220ff10a7389bde6324d`.
Copied all 67 exact modified/untracked nonignored files from D using
`git ls-files -m -o --exclude-standard -z`, structured PowerShell Copy-Item,
absolute-path containment and before/copy/after SHA-256 equality. D is untouched.
Existing D changes are inherited inputs, not track implementation.

Migration reserved: `20260909_0005_specialist_intake.py`; local predecessor
`20260908_0001`. Parent must linearize the integrated reserved migration chain.

## Current Truth And Bounded Implementation

At intake, manifest entries for all four slices were not_started/not_run/blocked.
Inherited source had no specialist typed record owner, child PRD or usable intake
for these ten domains. The shared capability catalogue correctly denies them.
The track adds independent typed intake, immutable correction history and exact
document-version observations; it does not pretend this completes every parent
legal journey. Mapping: DES/COPY/DOMAIN/LIC/ENF/GI/PVP/SICLD/TS/CUSTOMS-01,
IP-SCOPE-01 through 10, UJ-30 and UJ-41 through UJ-45.

Source legal support, authoritative rules, filing/registry operations, contested
processes, transfer/maintenance, delivery and exact-release acceptance remain
open. No deadlines, fees, current law, provider formats or legal text are invented.

## Parent Capability Request

Patent agent owns `services/ip_domain_catalog.py`; this track does not edit it.
Register only intake for the ten definitions exported by
`services/ip_specialist_contracts.py`: FACT_MODELS keys, LABELS,
CONTRACT_VERSION, contract_path, CHILD_PRD_HASHES and JOURNEYS. Preserve existing
required journeys as a union, never replace them with a smaller set. Licensing
keeps UJ-60/UJ-61 and adds UJ-30 to UJ-43; domain/enforcement request UJ-30 plus
the existing contextual UJ-45 gate. Final regression
`test_capability_request_preserves_existing_journey_gates` guards this boundary. Use
`intake_implemented=True`, with no authoritative jurisdiction/office claim until
the official source packs are accepted. Add independent `enforcement`; preserve
`customs_enforcement` for customs. All definitions must carry the exact pinned
child PRD. Service refuses writes if registration differs. No beta/GA evidence
is fabricated. Default isolated runtime therefore remains unavailable pending
parent integration; tests explicitly install reviewed intake definitions only
inside a scoped fixture and also regress the unchanged denied default.

## Catalogue Inputs

Ten exact pack requests are in the corresponding versioned child PRDs under
`docs/ip-implementation/child-prds/*-2026-09-09.md`: design legislation/rules,
copyright legislation/rules, registrar/UDRP/INDRP channel policies, tenant
agreement plus right-specific recordal sources, enforcement channel procedures,
GI statute/rules, PPV&FR crop-specific DUS/material and fee rules, semiconductor
layout statute/rules, tenant protection/custody/access sources, customs IPR
rules/notices/bond/fee/recordal scope. Every pack requires official bytes, source
version, issuing body/publisher, checked links and legal fixtures; a document's
presence alone is not source verification.

## Shared Hunks For Integration

- `db/models.py`: only import the three new specialist model classes.
- `api/router.py`: only import/register `ip_specialist.router` under `/api/ip`.
- `services/ip_domain_policy.py`: only extend RECORD_DOMAINS with specialist
  storage discriminators. GENERAL_DISCLOSURE_DOMAINS remains trademark-only.
- `services/ip_document_workflow.py`: explicit read-only history permits
  restricted specialist record types; mutations retain existing active guards.
- `services/matter_access.py`: `_validate_ip_access_change` rejects
  `set_restricted=false` for specialist record types with the typed 409
  `specialist_restriction_required`. Existing patent handling is unchanged.
- `apps/web/app/app/ip/page.tsx`: one link to `/app/ip/specialist`, immediately
  after the existing patent disclosure link. No other shared frontend change.
- Parent must regenerate OpenAPI/client and data-governance artifacts, register
  the three tables, update canonical ledgers/manifest and release selectors.
  Do not wholesale overwrite shared files from this worktree.

Exact shared anchors (apply only these additions, not the inherited files):

1. `db/models.py`, after `ensure_foreign_key_indexes`: import
   `IpSpecialistObservation`, `IpSpecialistRecord`, `IpSpecialistVersion` from
   `caseops_api.db.ip_specialist_models` with `# noqa: F401`.
2. `api/router.py`: add `ip_specialist` to route imports; add
   `application.include_router(ip_specialist.router, prefix="/api/ip", tags=["ip-specialist"])`.
3. `services/ip_domain_policy.py`: import `RECORD_TYPES as SPECIALIST_RECORD_TYPES`
   from `ip_specialist_contracts`; add `**SPECIALIST_RECORD_TYPES` to RECORD_DOMAINS.
4. `services/ip_document_workflow.py`, `_validate_target` explicit
   `allow_patent_history` branch only: import specialist RECORD_TYPES and extend
   the existing restricted `patent_family`/`patent_application` read allowlist
   with `*specialist_types`. The parameter name and all write guards are retained.
5. `services/matter_access.py`, start of `_validate_ip_access_change`: import
   specialist RECORD_TYPES; reject the restricted-to-open action before existing
   patent validation. No role, grant, ethical-wall or provider logic changed.
6. `apps/web/app/app/ip/page.tsx`: add a sibling Link with text
   `Specialist IP intake`, href `/app/ip/specialist`, and the existing patent
   link's `w-fit text-sm text-brand-700 underline` classes.

## Owned New Files

Backend (paths relative to `apps/api`):

- `alembic/versions/20260909_0005_specialist_intake.py`
- `src/caseops_api/db/ip_specialist_models.py`
- `src/caseops_api/schemas/ip_specialist.py`
- `src/caseops_api/services/ip_specialist_contracts.py`
- `src/caseops_api/services/ip_specialist.py`
- `src/caseops_api/api/routes/ip_specialist.py`
- `tests/test_ip_specialist.py`
- `tests/test_ip_specialist_postgres.py`
- `tests/test_ip_specialist_migration.py`

Frontend (paths relative to `apps/web`):

- `app/app/ip/specialist/page.tsx`
- `app/app/ip/specialist/[recordId]/page.tsx`
- `components/ip/SpecialistWorkspace.tsx`
- `components/ip/SpecialistWorkspace.test.tsx`
- `lib/api/ip-specialist.ts`
- `lib/api/ip-specialist.test.ts`

Other:

- `tests/e2e/iplf-090a-other-ip-domains-2026-09-09.spec.ts`
- `scripts/tests/run-other-ip-offline.sh`
- `scripts/tests/run-other-ip-web.sh`
- This evidence document.
- Ten `docs/ip-implementation/child-prds/<domain>-2026-09-09.md` files, where
  domain is exactly design, copyright, domain_name, licensing, enforcement,
  geographical_indication, plant_variety, semiconductor_layout, trade_secret,
  or customs_enforcement. Their exact hashes are CHILD_PRD_HASHES; tests compare
  actual bytes, not a self-reported version label.

## Implemented Boundaries

Three new tenant-scoped tables own the typed header, immutable facts versions,
and immutable source observations. Canonical IP docket/asset/grant/document/
lifecycle owners are reused. Observations require a real retained document
version, matching hash and locator; no legal effect is inferred. The selected
document must have exactly the one owned docket link on new writes. Read history
rechecks all current document links with bounded work. Supersession cannot branch
or cross a record, company or observation kind.

Creation and observations are idempotent, with replay reauthorization. Corrections
are optimistic under a fresh parent lock and append a reasoned version. Company
is locked before canonical parent rows. A source-change event invalidates old
private evidence on correction. A lifecycle-version change retires creation and
observation replay even after an explicit reopen on the same day. Restricted
terminal reads are explicit; ordinary writes and ACL broadening remain denied.
General AI, portal, export and notification eligibility are not enabled.

List queries enforce ACL before keyset pagination (up to 50) and never load facts
history or a full-count inventory. Source history is keyset-paged (up to 50) with
a 100-link authorization budget. UI uses server-owned client/type/source choices,
strict discriminated response validation, hydrated edit forms, frozen edit tokens,
retained rejected inputs, and authoritative mutation responses.

Governance integration request: register all three new tables as restricted
tenant evidence with immutable retained versions/observations. They are excluded
from general AI, portal, export and notification sinks. Preserve source/document
tenant lineage and actor lineage. Migration downgrade refuses retained evidence;
an empty rollback alone is not a data-deletion policy.

## Verification

All evidence files are retained separately under
`C:/tmp/caseops-other-ip-20260909`. Source tarballs include repository fixtures,
exclude only `.git`, and each has a SHA-256 sidecar. No real secrets are in these
artifacts. Test databases use an isolated test-only password.

| Attempt | Result | Retained evidence |
| --- | --- | --- |
| unit-01 | 15 passed, 11 failed, 0 skipped; 80.30 seconds | unit-01.jsonl/xml, source-unit-01.tar/sha256 |
| unit-02 | 39 passed, 0 failed/skipped; 149.89 seconds | unit-02.jsonl/xml, source-unit-02.tar/sha256 |
| web-01 | Frontend typecheck passed; 6 focused Vitest tests passed | web-01-typecheck.log (empty successful output), web-01.xml, source-web-01.tar/sha256 |
| pg-01 | 19 passed, 0 failed/skipped; 107.66 seconds | pg-01.jsonl/xml, source-pg-01.tar/sha256 |
| backend-03 | 60 passed, 0 failed/skipped; 452.38 seconds | backend-03.jsonl/xml, source-backend-03.tar/sha256 |
| pg-04 | 20 passed, 0 failed/skipped; 226.68 seconds | pg-04.jsonl/xml, source-pg-04.tar/sha256 |
| web-02 | Frontend and E2E typechecks passed; 6 Vitest tests passed; 3 PW journeys discovered (not executed) | web-02-typecheck.log, web-02-e2e-typecheck.log, web-02.xml, web-02-playwright-inventory.log, source-web-02.tar/sha256 |
| contract-05 | 12 passed, 0 failed/skipped; 0.33 seconds | contract-05.jsonl/xml, source-contract-05.tar/sha256 |

Every failure in unit-01 was inspected individually: ten journeys used the wrong
test DTO lookup (`document.policy` instead of the dedicated `/policy` response),
and one unauthenticated assertion retained the logged-in test client's cookies.
Tests were corrected to the actual contract and explicit cookie removal; no gate
or product permission was weakened. All 26 original identities are covered by the
replacement focused inventory. Journals were reconciled with 26/39/19 respective
setup, call and teardown reports and explicit completion events (exit 1/0/0).

A separate attempted web dependency-image build with `--network none` failed
inside npm ci ("Exit handler never called"). It produced no usable image and is
an infrastructure failure, not a product test result. The existing pinned
`caseops-web-test-tools:20260906` image supplied the offline dependencies for
web-01. No network or paid-provider workaround was used.

Backend tool image: `caseops-offline-test-tools:20260908-statute-compiler-isolated`,
with bash entrypoint. Unit containers: `--network none --cpus 2 --memory 4g`.
PostgreSQL: own `caseops-other-ip-pg-20260909`, pgvector/pgvector:pg17,
network none, 0.5 CPU/1 GB; test container shares only that network namespace at
1.5 CPU/3 GB. No host ports or other stack containers are used. Exec scratch is
checked for at least 2 GiB and actual executable permission; Temporal remains at
`/opt/caseops-test-tools/temporal-test-server`, hash
`daa58458d32f6254a901085c27ad1c19a64a4e171679ed08b5b92c298baba6ce`.

pg-01 proves all ten HTTP domain journeys on PostgreSQL, exact retained-source
download after lifecycle closure, source mismatch/supersession/replay, current
ACL and cross-tenant denial, same-day lifecycle replay rejection, a deterministic
stale-correction lock race, immutable evidence triggers and composite tenant FKs.
The 10,000-record list fixture includes 5,000 ungranted records and enforces at
most 12 SQL statements with zero version-history queries. The migration starts
from independently fresh template0 storage, upgrades the predecessor and new
revision, compares tables/columns/indexes/FK coverage/triggers, downgrades the empty
new tables and restores them. HTTP fixtures use only the pre-existing separately
migrated test-template helper, never a production/application database clone.

backend-03 includes 28 specialist unit tests, 19 specialist PostgreSQL tests,
one independent migration test and 12 inherited domain-boundary/exposure tests.
It adds a deterministic closure-wins correction race and retained-evidence
downgrade refusal. Its journal has exactly 60 setup/call/teardown reports, no
failure/skip and an exit-0 completion event.

The last test-fixture audit replaced a shared trademark-naming upload helper
with the UI's exact specialist-only multipart metadata. pg-04 reruns all ten
domain and five exception journeys plus both races, tenant/immutability/list
checks and fresh migration against that payload. Product behavior is unchanged;
the success-path proof no longer supplies a trademark mark/application number.
Only the explicit capability journey superset and its pure regression were added
after pg-04. Contract-05 verifies that final metadata and all ten pinned child PRDs.

Current owned backend files and five shared backend files pass Ruff
(`lint-final-03.log`); all six shared files pass scoped `git diff --check`.
`lint-final.log` retains a prior tool invocation
that tried to cache on a read-only mount; the successful replay uses --no-cache.
The final test fixture was separately formatted and linted after its audit.
Child PRD bytes are LF with the exact hashes in C; preserve those bytes through
integration and rerun pin tests after checkout/normalization.

The allocation map was checked against the structured manifest: exactly 51
unique rows (4 slices, 20 requirements, 27 paths), zero missing/extra/duplicate
rows. No browser execution, screenshots, production proof or source-pack legal
validation is claimed.

Final pg-04 and contract-05 journals each reconcile their full 20/12 setup, call
and teardown inventories with zero failures/skips and explicit exit-0 completion.
The final Docker inventory filtered by `caseops.track=other-ip-domains` is empty:
all test containers exited and the one owned PostgreSQL container was stopped.
No other container, stack, provider, source worktree or production resource was
mutated. No commit, push or deployment was performed.

## Remaining Closure Proof

- Parent must register the exact ten child contracts, linearize migration 0005,
  regenerate shared OpenAPI/client/governance outputs and rerun integration gates.
- The dated browser spec requires every domain to be positively intake-available,
  never skips missing registration, and exercises all ten intakes at 393/768/1280.
  It includes evidence upload, persisted reload, source observations, same-day
  close/reopen/second close, terminal byte-identical download and control bounds.
  It is not yet executed; screenshots, breakpoint inspection and exact-image
  browser outcomes remain unverified. The old f0 acceptance stack is not proof.
- General disclosure remains denied, not implemented: enabling AI, portal,
  export or notification for any specialist domain requires separate contracts
  and delivery-time/current-source/ACL/tombstone proof. No output channel may be
  inferred supported from this intake implementation.
- Full parent normal/exception journeys remain open: design registration,
  publication/renewal/cancellation; copyright ownership determination and licence/
  assignment/takedown; domain watch/UDRP/INDRP; licence royalty/fee obligations,
  recordal/termination; enforcement watch/right/Matter links and channel actions;
  GI authorised-user/registry workflows; plant DUS/material/fees/benefit-sharing;
  layout registration/use/cancellation; trade-secret disclosure incident response;
  customs bonds/fees/samples/release/disposal/enforcement actions. Retained source
  observations for these events are not substitutes for those workflows.
- No paid registry/provider, official legal automation, cold-start serving image,
  deployment, release-owned catalogue seed, or production browser proof has been
  attempted by this track. Parent owns those boundaries and canonical status.

Verdict: four assigned slices remain partial and full-domain claims are blocked.
This is a testable independent intake/source implementation, not COMPLETE IP.
The NO-GO applies to full-domain closure/activation, not a blanket prohibition
on the parent releasing compatible gated code after its own integrated gates.

## Exact Allocation And Product Gap Map

Reconciled directly against the structured PROGRAM_MANIFEST.yaml, not a summary
table: 090A and 091A have no directly allocated requirement/path IDs (explicit
administrative exceptions); 090B has 15 requirement IDs and 17 journey paths;
091B has 15 requirement IDs and 10 journey paths. The ten IP-SCOPE IDs overlap:
there are exactly 20 distinct requirement IDs and 27 distinct journey paths below.
Normal flows were also read from PRD sections UJ-30 and UJ-41 through UJ-45.

**Enabled full-domain functionality: NONE.** The inherited default capability
registry still denies new specialist intake. Scoped tests register intake only.
Parent registration can expose administrative intake, corrections, retained
document evidence and observations, not legal filing, prosecution, contractual
obligations or a validated domain lifecycle. The common `draft/ready/closed`
container lifecycle is administrative; it is not a design, copyright, GI or
other legal status machine. The UI is deliberately a common intake/evidence
surface driven by ten strict independent fact contracts. It is not evidence of
full-domain completion. No trademark application/particulars owner is introduced
or used to represent these rights.

Reference key (all are actual files/functions, not planned test IDs):

- S: `apps/api/src/caseops_api/schemas/ip_specialist.py`, its ten named Facts
  classes, SpecialistFacts and SpecialistObservation.
- P: `apps/api/src/caseops_api/services/ip_specialist.py`, create_record,
  correct_record, add_observation, get_record, list_records, list_observations.
- C: `apps/api/src/caseops_api/services/ip_specialist_contracts.py`, FACT_MODELS,
  RECORD_TYPES, OBSERVATION_KINDS, exact CHILD_PRD_HASHES and contract_path.
- D: `db/ip_specialist_models.py` and migration 20260909_0005 (paths above).
- UI: SpecialistWorkspace.tsx, SpecialistIndex/Form/Detail/Evidence/Lifecycle.
- T(domain): `tests/test_ip_specialist.py::test_domain_intake_and_source_journey[domain]`.
  PG(domain): `tests/test_ip_specialist_postgres.py::test_specialist_http_domain_journey_postgres[domain]`.
- Schema: `test_exact_child_prd_and_no_trademark_fields[domain]` and
  `test_all_nested_schema_objects_forbid_extra_properties` in test_ip_specialist.py.
- Gate: `test_default_catalogue_is_fail_closed_and_read_contracts_are_not_activation`.
- History: `test_version_history_stale_writes_identity_and_immutable_database`.
- Source: `test_source_failure_supersession_replay_and_domain_mismatch`.
- Access: `test_specialist_access_cannot_be_published_through_generic_acl`,
  `test_cross_tenant_cannot_read_or_mutate`, `test_terminal_history_download_and_revoke`.
- Lifecycle: `test_same_day_reopen_retires_creation_and_source_replays` and
  PostgreSQL `test_concurrent_correction_reloads_the_locked_parent[correction/closure]`.
- Frontend: SpecialistWorkspace.test.tsx (4 tests), ip-specialist.test.ts (2).
  PW: iplf-090a-other-ip-domains-2026-09-09.spec.ts, authored but NOT executed.
  These are intake tests, not implementations of the manifest's planned full
  `IPLF-UJ-*` test IDs.

### Slice Contracts

| Slice | Actual implementation/test evidence | Contract work still absent |
| --- | --- | --- |
| IPLF-090A | Five exact child PRDs; S Design/Copyright/DomainName/Licensing/EnforcementFacts; C; P; D; T/PG/Schema for those five domains; fresh migration and FK/immutability tests | Full type-specific legal state/relationship/obligation contracts, source/rule integration, mixed-revision rollout, governance registration, exact-release compatibility proof |
| IPLF-090B | UI and the five domain intake/source journeys; Source/Access/History/Lifecycle; six frontend tests; PW authored | All full normal flows and remaining exceptions mapped below; no domain legal activation or deployed acceptance |
| IPLF-091A | Five exact child PRDs; S GeographicalIndication/PlantVariety/SemiconductorLayout/TradeSecret/CustomsFacts; C/P/D; T/PG/Schema for those five domains | Material/custody/incident and rights-specific legal state/relationship/obligation owners, source/rule integration, governance and mixed-release proof |
| IPLF-091B | UI and those five intake/source journeys; Source/Access/History/Lifecycle; PW authored | Full specialist legal workflows, custody/channel delivery and their exceptions; no legal activation or deployed acceptance |

### Requirement Map

Every row remains partial or unimplemented at the full parent-requirement level.

| Requirement | Implemented code and actual test subset | Missing product behavior / proof |
| --- | --- | --- |
| DES-01 | S.DesignFacts; P facts/source journal; T/PG(design), Schema(design), History | Representation-set/application owner; filing/examination/registration/publication/renewal/cancellation and infringement links |
| COPY-01 | S.CopyrightFacts; unreviewed authorship/ownership/publication facts; T/PG(copyright), Source, frontend schema dispute test | Work deposit/rights chain, application/registration state, licence/assignment/takedown and litigation links |
| DOMAIN-01 | S.DomainNameFacts stores supplied domain/registrar/registrant/expiry/channel; T/PG(domain_name) | Registrar verification, renewal/watch, UDRP/INDRP case/response/transfer/cancellation and enforcement Matter |
| LIC-01 | S.LicensingFacts records parties/territory/field/exclusivity/term/confidential royalty text; T/PG(licensing) | Effective-dated grant/assignment, obligation/task/finance owner, recordal, renew/terminate/notices/reminders |
| ENF-01 | S.EnforcementFacts records represented party/asserted right/allegation/proposed channel; T/PG(enforcement) | Real watch-hit/right identifiers and lawful links, investigation/notice/platform/customs/opposition/cancellation/litigation execution |
| GI-01 | S.GeographicalIndicationFacts; supplied association/area/goods/specification/user claim; T/PG(geographical_indication) | Authorised-user owner, registry publications, opposition/registration/renewal/infringement workflows |
| PVP-01 | S.PlantVarietyFacts; category/denomination/species/applicant/breeder/farmer/material custodian/instructions; T/PG(plant_variety) | DUS/material chain, role claims, opposition/registration/fees/benefit-sharing/compulsory licence/cancellation/enforcement |
| SICLD-01 | S.SemiconductorLayoutFacts; creator/proprietor/exploitation facts; T/PG(semiconductor_layout) | Application/opposition/registration/use/licence/cancellation/infringement workflows |
| TS-01 | S.TradeSecretFacts stores references/control instructions, not a secret-substance field; restricted P/D; T/PG(trade_secret), Access, frontend secret-field rejection | Structured protection-agreement/need-to-know policy, disclosure-incident preservation/response, advisory/enforcement Matter links |
| CUSTOMS-01 | S.CustomsFacts stores asserted right/products/guide custodian/importer policy/instruction; T/PG(customs_enforcement) | Recordal/expiry, incident parties/goods/quantities/location, bonds/fees/samples, authenticity review, notice/release/disposal and enforcement chain |
| IP-SCOPE-01 | C exact child pin + P._registered/_writer; UI unavailable/intake-only; Gate/Schema | Parent registration and full-domain capability evidence; no supported-domain claim from storage |
| IP-SCOPE-02 | Ten S classes, dedicated record types, independent P writer; T/PG all domains; Schema rejects trademark_classes; existing Madrid/trademark regressions | Domain-specific legal state machines, fees/forms/party roles/deadlines; administrative lifecycle is not their substitute |
| IP-SCOPE-03 | P explicitly reuses client/docket/asset/document/grant/audit/lifecycle owners; D tenant FKs; T/PG/Access/Lifecycle | Typed party/relationship/task/obligation/billing/notification adapters for specialist legal operations |
| IP-SCOPE-04 | S jurisdiction_as_supplied is an unverified fact; C registration request has empty authoritative jurisdiction/office support | No jurisdiction/office legally supported; per-office source-backed rule selectors and qualification tests absent |
| IP-SCOPE-05 | T/PG normal intake; Source/Access/Lifecycle/History; fresh migration; stale races | Contested/transfer/renewal/maintenance and all complete domain-specific normal/exception flows, browser execution |
| IP-SCOPE-06 | No legal rule engine or invented legal fixture is added | Two-reviewer deadline/form/fee fixtures and rule-update historical-obligation tests absent |
| IP-SCOPE-07 | Distinct asset and domain/client identity; S/P immutable identity; T/PG, History | Cross-right family graph, effective-dated ownership/territory/encumbrances, source-backed chain and consolidated client view absent |
| IP-SCOPE-08 | ip_domain_policy excludes every specialist record from general disclosure; explicit source reads + restricted ACL guard; T/PG all source policies and Access; existing patent projection denial regressions | No specialist-specific saved-output/delivery race matrix or authorised exception/publication channel; no general disclosure enabled |
| IP-SCOPE-09 | P.contracts uses server capability and exact contract registration; UI label and disabled create; Gate + frontend unavailable test | Parent packaging/reporting/catalogue integration and beta/GA exact-release evidence; no beta/GA claim |
| IP-SCOPE-10 | Versioned child contracts, this complete gap inventory, migration/PG query/race/ACL tests, fail-closed capability request | Legal/source packs, complete product journeys, support operations, mixed rollout and exact-release matrix; no M8-M10 exit |

### Journey Map: IPLF-090B

"Subset" means the cited test proves only the stated bounded behavior; the planned
full manifest test remains open. "None" means no functional implementation/test
of that requested behavior, even when a descriptive intake field exists.

| Exact path | Code/test evidence, if any | Remaining requirement |
| --- | --- | --- |
| UJ-30-NORMAL | Subset: S/P/UI typed facts and exact source journal; T/PG(design,copyright,licensing) | Legal prosecution/recordal/renewal/enforcement, obligations/deadlines, related right/Matter links and validated per-type lifecycle |
| UJ-30-EXC-01 | Subset: S discriminators + P access; Schema all domains; T/PG no TrademarkApplication; Access | Type-specific engagement/role policy beyond canonical IP capability + restricted grants; full legal forms |
| UJ-30-EXC-02 | No contractual/registry deadline writes exist in P; no success-path obligation test | Implement contractual obligation owner separate from registry deadlines, then prove separation with actual obligations |
| UJ-41-NORMAL | Subset: DesignFacts and source journal; T/PG(design) | Filing package, examination/objection/response/hearing, registration/publication, renewal/assignment/cancellation/infringement, reports/rules |
| UJ-41-EXC-01 | Subset: immutable facts/document-version references; History + Source | A revised representation SET with multiple members/versions is not implemented or tested |
| UJ-41-EXC-02 | None | Jurisdiction-specific variant/multiple-design relationship rules and tests |
| UJ-41-EXC-03 | Subset: publication_instruction enum and restricted evidence; S.DesignFacts, T/PG(design) | Publication effective-time instruction/review/execution and confidentiality timing tests |
| UJ-41-EXC-04 | None; observation vocabulary does not create a proceeding | Independent cancellation proceeding, parties/grounds/outcome/linkage and tests |
| UJ-42-NORMAL | Subset: CopyrightFacts and exact sources; T/PG(copyright) | Rights chain, deposits, application/deficiency/objection/hearing/registration/correction/expungement, licences/notices/settlement/litigation and reporting |
| UJ-42-EXC-01 | Subset: ownership_claim and ownership_disputed; frontend dispute schema test; P observations legal_effect=not_determined, Source | Multi-party competing claims with evidence, review and resolution workflow/tests |
| UJ-42-EXC-02 | Subset: P never derives a legal right from an observation; T/PG(copyright) asserts not_determined | Actual registration journey proving underlying rights remain independently represented |
| UJ-42-EXC-03 | None for platform handling; neutral observations cannot update legal status | Platform response vs court/registry disposition owners and linked success/exception tests |
| UJ-43-NORMAL | Subset: LicensingFacts and page-pinned evidence; T/PG(licensing) | Grant/transfer/interest periods, sublicensing/controls/minimums/reporting/audit, approved terms, obligations/task/finance, recordal/notices/termination |
| UJ-43-EXC-01 | Subset: no automatic legal interpretation; S interpretation_issue is supplied text | Lawyer review/approval of extracted terms and permissions; no functional review test |
| UJ-43-EXC-02 | Subset: optional interpretation_issue stores a note, Schema(licensing) | First-class review issue, owner, resolution, dependencies and tests |
| UJ-43-EXC-03 | Subset: royalty_terms_confidential remains restricted and general disclosure denied; T/PG(licensing), Access | Dedicated confidential-term redaction tests with actual populated financial terms across ordinary portfolio/client/saved outputs |
| UJ-43-EXC-04 | Subset: administrative closure retains all facts; History/Lifecycle | Effective-dated permission/ownership periods and actual contractual termination without period deletion |

### Journey Map: IPLF-091B

| Exact path | Code/test evidence, if any | Remaining requirement |
| --- | --- | --- |
| UJ-44-NORMAL | Subset: four exact S contracts and source journals; T/PG(geographical_indication,plant_variety,semiconductor_layout,trade_secret) | Type-specific filing/opposition/registration/fees/licences/cancellation/enforcement, rules/reporting, legal fixtures and SME acceptance |
| UJ-44-EXC-01 | Subset: Gate denies unregistered create; strict S rejects generic trademark fields; existing domain-boundary tests | Complete disabled-domain creator inventory after parent integration, including any future adapters |
| UJ-44-EXC-02 | Subset: no secret_substance field, general disclosure denied; frontend schema rejection, T/PG(trade_secret), Access | Specialist-specific stale/saved projection and publication/delivery race matrix; intentional authorised secret AI processing remains unavailable |
| UJ-44-EXC-03 | Subset: custodian/access instructions and current grant checks; S.PlantVarietyFacts, T/PG(plant_variety), Access | Biological material custody/action policy and material-specific access/revocation tests |
| UJ-44-EXC-04 | Subset: all intake/evidence is restricted, general outputs excluded; T/PG/Access | Separate public registry/source projection and confidential know-how controls with both populated paths |
| UJ-45-NORMAL | Subset: CustomsFacts + retained source observations; T/PG(customs_enforcement) | Recordal renewal/expiry, detention incident details, response deadlines, client/authenticity review, sample chain/inspection/notices/outcomes/costs/proceedings/watch integration |
| UJ-45-EXC-01 | Subset: restricted documents and guide-custodian reference; T/PG(customs_enforcement), Access | Guide-specific narrowly scoped roles/grants separate from whole-record access, and those fixtures |
| UJ-45-EXC-02 | Subset: P observations always legal_effect=not_determined; T/PG(customs_enforcement) | Authenticity review states/approvals and a populated suspected-versus-confirmed workflow test |
| UJ-45-EXC-03 | None | Durable urgent obligation/escalation outbox and external-channel failure/recovery tests |
| UJ-45-EXC-04 | Subset: neutral journal cannot alter legal outcome; T/PG(customs_enforcement) | Real seizure/release action linked to separate infringement determination, plus explicit outcome tests |

No full-domain journey above is closed by the common record UI. Missing legal
authority is separate from missing repository functionality: both are itemized;
source packs alone would not implement the missing workflows.
