# IPLF-073A/B Access-Review Campaign

Independent continuation after the 37-file foundations handoff was frozen at
`C:/tmp/caseops-foundations-handoff-20260910`. That handoff and its failed evidence
remain unchanged. No parent-worktree edits, commits, pushes, or production work.

## Exact Product Scope

An authenticated owner/admin with `matter_access:manage` opens one campaign for
one currently visible Matter or IP docket, selecting a server-resolved target.
The campaign retains every unrevoked explicit membership/team grant (maximum 20),
including its version, original reason, effective dates and subject label. It does
not renew expired grants or create permissions. A separate user records immutable
keep/revoke decisions. Neither the preparer nor a grant's membership/team subject
can certify that grant. A current non-reviewing access administrator finalizes
all decisions against the current target policy and grant/team snapshot.

Canonical grant writes remain in `services/matter_access.py`: IP uses its existing
preview/apply owner; Matter uses its existing remove owner. The opt-in `commit=False`
adapter lets all revocations, private invalidation events, and campaign finalization
commit atomically. Existing callers retain default commits. Both access responsibility
fences now enter Company-first before memberships and record locks.
The team-scoping entry also takes Company first, keeping the same order when a
concurrent scoping change wins or waits for a campaign finalization.

The UI is `/app/admin/access-reviews`, reached from Administration. It includes
record-title search and bounded continuation, scope discovery, MFA step-up using
`record_access_change`, current grant evidence, independent decisions, finalization,
typed errors and retained register/detail reload. It is not an emergency-grant UI.

## Ownership And Integration

- New migration: `20260910_0001_access_review_campaigns.py`. Local predecessor is
  `20260909_0003`; parent must linearize reserved revisions on final integration.
  Migration 0003 is untouched. Populated review evidence blocks downgrade.
- Shared models: insert only `AccessReviewCampaign` and `AccessReviewDecision`.
  No replacement of the shared models file or any frozen preservation model.
- Parent owns data-map, event-catalog, generated projection, OpenAPI and programme
  manifest integration. The two new tables must be registered as retained access
  review evidence, with restricted internal read authorization and no independent
  grant/export/purge authority. The parent reported its preservation integration
  passed 289 tests / 867 phases in `foundations-integration-01`, closing the prior
  missing-table failure there. That result is not evidence for these new tables
  or any access-review code, and the original failure evidence remains retained.
- Audit actions to register: `access.review.created`, `access.review.decided`,
  `access.review.finalized`; target `access_review_campaign`; Matter/IP context
  remains correlated. Finalization records original snapshot hash, revoked grant
  identities, final access version and canonical IP invalidation operation IDs.
  Catalog owner is `platform-shared-foundations`; the parent/summary owner should
  register these once with the new campaign regressions during shared integration.
- Existing foundation DTOs still list campaigns in `excluded_persistence` because
  the shared catalog contract is parent-owned. Integration must distinguish the
  now-implemented campaign adapter from still-unimplemented emergency sessions.
- No shared summary-agent event catalog edits were made here. No callable
  subagent messaging surface is available in this continuation.

## Requirements And Remaining Scope

IPLF-073A supplies the additive campaign contract/storage/owner adapter. IPLF-073B
supplies this specific user journey, not all of its reciprocal programme allocation.
The primary campaign requirement is SEC-GOV-04; independence is SEC-GOV-02,
step-up SEC-GOV-01, current tenant/record authorization IP-ACCESS-01/03,
internal-only scope IP-ACCESS-04/05, and canonical invalidation IP-ACCESS-06.

Both programme slices remain partial overall. Still open: scheduled campaign
creation and automatic trigger ingestion; firm-policy deadlines, escalation or
automatic expiry of unreviewed grants; client-wide and portal-grant campaigns;
emergency-access sessions, their scoped capabilities, notifications, action log,
expiry/cache/session revocation and retrospective review (SEC-GOV-03 and all
UJ-63 normal/exception paths); the remaining SEC-GOV and IP-ACCESS reciprocal
requirements; shared-catalog integration and exact-release deployed acceptance.
No standing-grant residue claim is made for the unimplemented emergency journey.

## Verification

Evidence is appended under `.tmp/ip-access-review-evidence` with new run labels.
API/PG uses `-p tests.retained_results` and `CASEOPS_TEST_RESULT_JOURNAL`; completion
requires `session_finished`. Runs use at most a combined one CPU and 2 GiB for
owned active containers. All test transport is offline/no-paid. No full heavy gate.

Initial `access-review-api-01`: four passing, four failed complete call observations.
Each of the four failures was inspected: successful finalization serialized a UTC
suffix that SQLite reload omitted. Fixed in typed DTO UTC normalization; the exact
unchanged reload assertion passed in `access-review-pg-01` (34 total passing nodes,
including seven PostgreSQL tests and the adjacent canonical access-owner suite).
Current runtime verification: `access-review-pg-02` passed all 85 nodes, with all
255 setup/call/teardown phases reconciled and no skip/failure. This includes 14 API
nodes, 15 PostgreSQL nodes, and 56 adjacent canonical access/team/role-fence nodes.
The PG tests cover both targets, stale grant/reviewer/team-scoping races in both
lock orders, immutable retained evidence, atomic multi-revoke rollback, bounded
history/reads, and independently fresh migration upgrade/downgrade/reupgrade.
`access-review-api-03` passed 14 nodes / 42 phases after strengthening direct
cross-tenant mutation assertions with valid foreign-tenant step-up.
The expanded `access-review-pg-03` then passed all 18 PostgreSQL nodes / 54 phases,
including those direct foreign-tenant commands, stale snapshot/version rejection,
and current reviewer/expired-step-up rejection, plus the complete earlier PG
inventory. No runtime code changed between the 85-node gate and this expansion.

`access-review-web-01` passed 12 unit tests and TypeScript, then failed normal
Playwright collection because the new spec lacked the required slice suffix.
The spec was renamed to `iplf-073b-access-reviews-2026-09-10.spec.ts`; no shared
discovery rule was weakened. Its unchanged frontend assertions passed again in
`access-review-web-02`: 12 tests, TypeScript, and two normally discovered browser
nodes. `access-review-browser-02` passed both Matter and IP docket journeys with
zero retries, skips or flaky outcomes, against a fresh offline build. Each journey
proves UI creation, independent decision, canonical revocation, both actors' reload,
and stale finalization rejection. Responsive checks cover 1280/800/768/767/390/360px;
desktop/mobile screenshots were inspected. The offline banner is expected in the
network-disabled fixture. `access-review-lint-closure` passed all new Python files
after the final PostgreSQL selection expansion. Per-file reconciliation proves
the tested backend and fresh-browser runtime bytes equal the handed-off source.

Read/work ceilings are explicit and fail closed: 25-row keyset pages, 20 grants per
campaign, 200 tenant memberships, 400 reviewed team links, and bounded preflight
before canonical execution (100 tenant teams, 400 tenant team links, 20 linked
dockets, and 256 retained rows per relevant operational/grant/wall model). Retained
history is charged before active-row filtering; overflow cannot partially revoke.

New sibling JSON artifacts contain complete per-node phases, retained failures,
browser/frontend outcomes, resource/source proofs, exact owned-file hashes and
per-slice canonical requirements with remaining gaps. Shared models/router/admin
changes are merge-only hunks, not authority to replace inherited work. All owned
containers are stopped and retained. This is focused local feature evidence, not
whole-program completion or production acceptance.
