# Export Resource Readiness Correction

Ownership: IPLF-030B/037, UJ-04-NORMAL/EXC-02/EXC-03, J08/M08,
NFT-005 and SEC-003/004. This repairs the release boundary for the portfolio
worker, not an unrelated marketing or app feature.

## Actual Failure

PR566 merged as `b9946c71f7e9912d56b5372f2dcfedd3cf82eea6`, with the
same tree as the accepted local Docker candidate:3425 PostgreSQL passes,
1906 frontend passes and630 browser passes/10 explicit browser skips. Main
CI40518507908, Security40518507923 and CodeQL40518508002 succeeded.

The guarded production attempt completed both image builds, backup, migration,
seeds and job reconciliation, then stopped before API/web routing. Cloud Tasks
API enablement had actually succeeded. A filtered `gcloud services list` with
`--limit=2` returned an empty list because the limit preceded client-side
identity filtering. A full69-row enabled inventory and exact Service Usage GET
independently prove ENABLED. The fake CLI had supplied the desired row without
modeling this boundary. The adjacent secret-existence check used the same
unsafe filtered-list assumption.

The stopped attempt did not create the worker secret or queue and did not
deploy the new API/web. Fresh marked identity at17:02 UTC still reports
`f49b274e2098cdbd0284e505c2eb5fc363b820d2` on API00504-478/web00481-qbn.
Do not call B994 deployed or certify its worker from successful infrastructure
phases. Existing product export acceptance remains open from QA40323857026.

## Correction And Boundaries

- Read the exact owned Cloud Tasks service with Service Usage GET. Validate
  numeric project, full service identity, config name and ENABLED/DISABLED state.
- Read only the owned Secret Manager secret metadata. Accept absence only from
  a bounded HTTP404 with the matching typed NOT_FOUND body. Permission, server,
  malformed and oversized responses fail closed; no secret payload is read.
- Keep management hosts, resource identity, current main, runtime, IAM, queue,
  HMAC, deadlines and no-retry boundaries unchanged. No App Engine bootstrap,
  new terms, broad IAM, test task or billable legal/model call is introduced.
- Report only an allowlisted static failure phase. Never expose raw CLI output,
  OAuth material, response bodies or exceptions in release errors.

EXW-MD01: real CLI false-absence reproduction for both exact metadata resources.
EXW-MD02: exact service/project/config/state identity, including disabled state.
EXW-MD03: exact owned secret identity and positive/typed-absent readback.
EXW-MD04: denial, server, malformed, oversized and inconsistent404 responses.
EXW-MD05: management host/method/path/missing-response scoping and no payload.
EXW-MD06: static phase redaction and unchanged full provisioning/verification.
EXW-MD07: full deploy rehearsal, canonical release and actual IP18 desktop/mobile
51-row export within the unchanged15-second budget.

## Retained Evidence And Remaining Gate

The first frozen follow-up `367176d8` encountered new Security40548963348
advisories: dnspython CVE-2026-114605 and fpdf2 CVE-2026-114609/114610. Their
reviewed GitHub records were published after the prior main security acceptance.
Docker08 was explicitly cancelled during image build, before stack/product tests;
it remains incomplete. The replacement raises only the two package floors to
the published patched2.9.0/2.8.8 floors, resolves only dnspython2.9.0 and the
current stable fpdf2 2.8.9, refreshes their lock entries and adds
manifest/lock/installed-version plus deterministic offline DNS parser coverage.
The patched local environment passes strict OSV pip-audit with no known
vulnerabilities, and all154 installed packages satisfy dependency compatibility.
Existing PDF layout/native compatibility, email/admin/report and full acceptance
must pass on that new candidate. No advisory ignore or threshold change is used.

The twelve-module component selection on367176d8 collected380 intended cases:
331 non-PostgreSQL cases passed with993 phases;49 PostgreSQL identities remain
pending the canonical replacement. This is not a completed full Docker result.

The same complete component inventory was repeated on2046e2d9:331 passes,
993 phases and49 PostgreSQL identities still reserved for Docker. Its fresh
Security and CodeQL passed. Full frontend04 instead finished1905passes/1failure
of1906: the real-provider reports entry did not observe its account label within
the unit query wait. The retained prettyDOM is truncated before the report body,
so it cannot establish whether authentication or report delivery was pending.
The proposed test-only correction explicitly controls both real-client response
stages inside React act, preserves anonymous/MFA gates and proves a late response
cannot expose activity after invalidation. Do not alter production deadlines,
weaken schema/role checks or call an isolated rerun complete frontend acceptance.

The unchanged three-case diagnostic passed, so the precise original slow stage
remains unproved. The four controlled page cases and complete adjacent reports,
session and client modules pass62/62 with zero skips/errors, matching JSON and
JUnit. All real-provider/client/schema boundaries remain. The closest analogous
admin-entry fixture was reviewed; it and the six other platform entry modules
passed frontend04 and are unchanged. Full replacement frontend acceptance is
still required, with1907 intended cases after the added invalidation regression.

Both old-source reproduction cases failed as expected. Expanded local run02
was incomplete:141 call passes and one setup/teardown error from a two-million
character parametrized ID exceeding Windows environment limits. That is a
fixture defect, not an executed product case. Explicit bounded IDs and
in-test payload construction corrected it without weakening response bounds.
Complete replacement green03 passed142/142 with zero skips in1.46seconds;
its collection, setup/call/teardown, XML and original failed evidence remain in
`outputs/fix-561-20261026/portfolio-export-worker` under the primary workspace.
The exact dirty-source read-only probe at16:52 UTC independently confirmed
service ENABLED and typed secret absence, with zero management mutations.

The stopped release had also held business worker admission. At17:09 UTC the
unchanged canonical scheduler reconciler restored the three existing document,
court and tracked-case schedules and their worker admission. An initial resume
correctly refused held admission drift; no raw toggle bypassed that guard.
Private maintenance and the unreleased export-recovery cadence remain held.
Interim ordinary maintenance is health evidence, not post-QA resume authority.

Verdict: Partially fixed. The new correction still requires its own frozen
source, full intended Docker/CI inventory, protected merge, guarded exact-main
deployment, complete production replacement and later clean cadence evidence.
Preserve legal-review, Ram's external cleanup, owner-MFA and native platform
holds separately. No synthetic leads, paid probe or current GSC result is
claimed from these engineering checks.

Primary references:
[Service Usage get](https://docs.cloud.google.com/service-usage/docs/reference/rest/v1/services/get),
[Secret Manager metadata get](https://docs.cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets/get).
