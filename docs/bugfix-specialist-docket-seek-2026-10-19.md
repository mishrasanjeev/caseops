# Specialist Docket Lookup Recovery

## Scope And Verdict

IPLF-090/091, UJ-30/41 and the existing specialist/access owners retain scope.
This fixes the list reader, not legal-source verification, provider activation,
Google consent or the unidentified historical Matter incident. Verdict:
**Partially fixed in source. Production acceptance remains pending.**

## Actual Failure And Cause

PR545 merged as `401d16159a58ee0cd7bb224b66e72e09b4ad6a48`, with the exact C5
tree. Its hosted acceptance passed, but local Docker15 did not. Native groups
1-4 completed1604 cases:1603 passes/one failure; group5 has no executed phase,
and later native/browser coverage is incomplete. All failed evidence is retained.

The10k specialist listing charged390055 executor-work units against the
unchanged2048 limit. Its52 docket lookups used `ix_ip_docket_company_status`,
removing7487 rows per loop:389376 work from this node alone. The same-source
hosted plans used a different index and passed at731-1231 work. Thus a green
hosted run did not establish plan-independent boundedness. Neither timeout nor
statement count alone would have diagnosed the repeated broad scan.

## Correction And Adjacent Audit

Reuse the existing patent reader's nonflattenable key barrier and SQLAlchemy
ClauseAdapter pattern. Seek one PK successor, then require the exact docket ID,
tenant, record kind, restricted state, current ACL and requested lifecycle.
No candidate-page limit is applied before authorization. Cursor ordering,
response fields, grant/wall windows and closed-history semantics are unchanged.
The shared access-policy module, indexes, migrations and budgets are unchanged.

A compile-only prototype exposed unadapted bare ORM Boolean attributes adding
an unrelated base-table FROM. Explicit Boolean expressions plus two committed
SQL-composition guards prevent that error. Six native cases cover owner without
grant, membership/team walls, closed history and present wrong successors under
own/foreign tenants. The neighboring shared-policy consumers remain covered by
their existing gates; this failure is not evidence every ordinary join is broken.

The committed OTHER-IP-090/091 browser journey now also locates the saved design
record in the actual authorized list, follows server-owned pagination, checks
visible identity/controls at393/768/1280px and opens that exact record. Existing
source, closure/reopen/reclosure and retained download assertions remain.

## Verification And Limits

Retained artifacts are under `outputs/ip-calendar-open-items-20261017` in the
primary workspace, separately from this clean release worktree:

- `docker15-cancellation-01/failed-specialist-plan.json`: actual work failure.
- `docker15-cleanup-reconciliation-01`: complete prefix, zero-phase interrupted
  group5, source identity and exact resource closure.
- `specialist-native-red-01`: operator setup failure because an internal Docker
  network supplied no host port; zero tests. Both owned resources removed.
- `specialist-native-red-02`: complete19 cases/57 phases,18P/1F on the new seek
  assertion. This fresh plan happened to satisfy the old work bound; it is not
  another390055-work reproduction.
- `specialist-native-green-01`:19P/6F/75 phases. The original19, including all
  four plans, passed. Six new cases stopped at UUID/string expectation errors
  before their security assertions; these are not successful bug reproductions.
- `specialist-native-green-02`: complete25P/75 phases, zero skips/errors, natural
  exit0, identical source before/after and owned DB/network cleanup. Four plans
  measure1100/1000/1485/1315 work, each a one-row PK seek. Only typed expected
  identities changed after the prior six test failures; no assertion was removed.
- `specialist-query-unit-01.xml`: two compile guards passed. Focused ruff and
  governance-map validation also passed.
- `specialist-sqlite-results-01/02`: each completed24P/10F. Every failure was
  the raw child-PRD fingerprint assertion after CRLF checkout conversion, not
  the list reader. An initial checkout-index command returned0 without changing
  existing bytes; the second failed run is retained. Pin child-PRD Markdown to
  LF and mechanically restore only14 clean files after retaining raw backups.
  Each restored raw Git blob exactly matches HEAD; fingerprints stay unchanged.
- `specialist-sqlite-results-03`: complete34P/102 phases in the three intended
  modules, with the original inventory retained. All ten exact contract hash
  assertions now pass. `child-contract-checkout-normalization-01` retains the
  original bytes and exact per-file canonical Git-blob equality.

These are scoped source proofs, not full local Docker, fresh candidate/main CI,
or production certification. Last observed serving API/web is `9cf76f2b`; its
full production run39143613520 failed385P/1F/18 explicit skips despite all50
dated IP/Calendar journeys passing. Private cadence remains paused. The consumed
test-legal-only manual-IP grant must not be replayed. Both workbook histories
must distinguish current row acceptance from global release certification.
