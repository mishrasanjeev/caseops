# AI Requirements Evaluation

## Source And Scope

The owner supplied `CaseOps_AI_Requirements.docx` version 2.1 on 7 November.
SHA256: `1f6cbe12e130e9fe83a971b1067e9eb05fc90bbfe0094d37b2ece22bb4cdb1bf`.
The document contains 30 numbered sections, 767 nonempty source blocks and
60 proposed acceptance scenarios. It explicitly describes a target state, not
current implementation. It contains screenshot descriptions but no embedded
screenshots. Headings, table headers, fields and acceptance scenarios must not
be inflated into a bug count.

The initial main/API/web baseline was
`d2a172f7922f755ccd10da967df61840b2237fb8`, API00520-csl/web00495-qsx.
Its separate QA42311071636 succeeded. That result does not certify this new
candidate, its new browser journeys or all requirements in the document.

Independent domain reviews mapped 602 source blocks; the remaining 165 are
front matter and cross-module objectives, relationships, benchmarking,
acceptance, sequencing and external decisions. The workbook retains all 767
ordered blocks, their classification and assessment, all 60 acceptance aliases
and 84 finding/subsection groups. Those groups are not 84 independent bugs.

## Bounded Software Findings

All current release verdicts are **Inconclusive** until complete local Docker,
CI, Claude quality review and exact-serving production Playwright acceptance.

| ID | Source And PRD | Finding | Candidate And Required Proof |
| --- | --- | --- | --- |
| AI-B01 | AI-R0265/0280; J14/M13/US-040/FT-059 | Existing team-member lead changes returned before audit recording. | Record authenticated tenant/actor and before/after only on actual change; no duplicate audit on identical replay. Complete test_teams.py passed 8 cases/24 phases on SQLite; browser and PostgreSQL/release proof remain separate. |
| AI-B02 | AI-R0222/0258, CON-T03; J10/M09/US-029/FT-050 | DOCX redline parsing omitted tracked changes in table cells. | Walk body/nested paragraphs in original XML order, avoid merged-cell aliases and nested paragraph double counting. Full test_contract_intelligence.py passed 35 cases/105 phases locally. This is not full two-document comparison, accept/reject or clean/tracked export completion. |
| AI-B03 | AST-T01..04; J03/J14/M14/M16, IPLF-062B | Assistant source controls followed cached URLs without the existing click-time authorization/audit endpoint. | Resolve through the authenticated open endpoint, validate its exact current workspace destination and reject unsafe/error responses without cached fallback. Destination routes may independently enforce ACL; no disclosure incident is established. |
| AI-B04 | AI-R0398..0420; IPLF-062B | Reopening a retained conversation showed only the oldest 50 turns and discarded continuation. | Keep bounded ordered pages, deduplicate identities, preserve server cursors and reject late responses after a session switch. Local fixture provisioning and complete browser proof remain required. |
| AI-E01 | AI-R0263..0289, TEAM-T01..03; J14/M13/US-040 | Team membership APIs existed but Teams had no member/lead management controls. | Add eligible colleague selection, lead toggles, confirmed removal, pending-command fencing, input-preserving errors and responsive layout. This does not close the entire invite, workload and notification program. |
| AI-B05 | AI-R0585, supporting AI-R0568..0575; IPLF-038B/052B | Watch report dispatch used an empty stub instead of retained captures/reviews. | Candidate joins authorized current dockets, profiles and visible publication evidence, caps hydration and computes complete SQL totals. Automated journal coverage remains explicitly unavailable. Baseline reproduction, candidate controls, PostgreSQL and positive browser/export proof remain required. |
| AI-B06 | AI-R0585 and shared report readability; J13/M12/IPLF-038B | Nested report cells kept machine enum values and internal identifiers even though top-level cells were readable. | Apply the same readable-code and identity/hash omission recursively to report cells only, preserving the separate generic formatter and free text. Two new baseline unit failures are retained; complete unit and built-browser replacement remain required. |

## Target-State Enhancements And Dependencies

The existing calendar, contracts, teams, research, assistant and IP modules are
not absent merely because a requested end-to-end path is incomplete. Reuse
their source-owned IDs, lifecycle, rules, notifications and audit services.

Valid additional software scope includes broader linked calendar sources and
filters, complete structural Word editing/comparison/accept-reject exports,
contract approvals/execution obligations, richer team assignment/workload,
portfolio drill-downs, reviewed multilingual legal outputs, multi-docket
recordal transactions, additional report exports/recurrence, expanded patent
intake and source-aware product help. Existing narrower paths must be preserved.
Each enhancement needs its complete original acceptance, not a cosmetic tab or
mocked happy path. The source prioritization is proposed sequencing, not a
delivery-date commitment.

Missing approved rules/calendars, exact legal source evidence, licensed registry
adapters, lawful jurisdiction coverage, user consent, independently reviewed
forum templates and language benchmarks are external prerequisites. Safe
abstention, an unverified date or a paused provider is not automatically a code
defect. No invented legal identity, rule, holiday calendar, provider result,
approval or generation-quality score may be used to close a row. Automated
tests remain no-paid; local behavioral tests use deterministic providers and
production consumes authorized retained evidence rather than billable probes.

## Why Prior Closure Was Insufficient

The recurring quality risks are specific and preventable:

1. Source code or an API response was mistaken for a persisted user outcome.
   A visible tab does not prove save, reload, permission and export behavior.
2. A narrower primitive was mistaken for the original contract. A paragraph
   redline fixture did not exercise tables; one history page did not prove a
   retained conversation remained reachable.
3. A local tree was mistaken for the serving revision. Every closure must name
   the exact built image, API/web SHA and dated deployed browser result.
4. Proposed scenarios, discovered files, skipped tests and successful components
   were mistaken for complete executed acceptance. Reconcile every identity and
   keep failed, skipped and unexecuted work visible.
5. A failing test was changed before its failure phase was understood. Here an
   implicit mock return became a Vitest cleanup callback. The original exact
   rejection assertion is retained; setup hooks in the two adjacent IP API test
   modules are corrected too. Failed receipts are preserved.
6. Configuration/source gaps were conflated with defects. Repair software
   without removing legal, access, lifecycle, cost or source-verification fences.

The corresponding durable rules are in AGENTS.md. New regression work includes
team actor/tenant audit lineage and replay, table-only/mixed/nested/merged DOCX
changes, unsafe citation destinations and revoked sources, 50/200-turn history,
late-session responses and private-cache removal after unsafe failures.

## Matter Reopening

No affected Matter ID, incident time or persisted incident audit was supplied.
The bounded source review did not demonstrate accidental reopening. Current
source has dedicated locked disposal/reopen commands, optimistic tokens,
disposed generic-write rejection, operational-child neutralization and audits.
An explicit authorized Disposed-to-Intake transition and later Intake-to-Active
transition are not, by themselves, automatic resurrection.

Keep the existing lifecycle safeguards. Diagnose a real incident using the
successful disposal response, exact serving version, persisted status/activity
flag/lifecycle version, subsequent actor/reason/audit and initiating request or
worker. Existing lifecycle/PG/browser regressions were inventoried, not rerun
as part of that read-only audit. Incident verdict remains Inconclusive.

The separate local component replay subsequently passed the complete 17-case
Matter lifecycle file. This proves those controls on SQLite only, not an
unidentified historical incident, PostgreSQL concurrency or production closure.

## Local Verification Checkpoint

Complete local API modules passed 8 Teams, 35 contract-intelligence and
17 lifecycle cases. Six frontend files passed 106 cases, including a new
pending-checkbox/rollback case. Fresh web builds and E2E typecheck passed.
The earlier evidence-writer module passed 655 cases/1,965 phases. The final
resolved app inventory moves from 714/53 desktop/mobile to 718/55: exactly
six added cases, no dropped prior identities. The complete writer replacement
passed all 655 cases and 1,965 phases at those final counts. Production tester discovery includes both
Teams and contract widths; the separate assistant retained-history role
requires genuine hash-pinned evidence and cannot manufacture production turns.

Failed local browser run01 is preserved (two fixture refusals and two checkbox
interaction failures). Run02 passed three of four: one citation/paging journey
and both Teams widths. Its remaining assertion incorrectly included Next's
empty route announcer outside the workspace; the corrected assertion still
requires zero workspace error alerts and byte-pinned other-session turn IDs.
Run03 then passed all six intended changed/existing journeys without retries.
Run04 added both complete Watch journeys: the retained data and review passed,
but both widths failed on the nested machine-state rendering. That is a new
adjacent defect, not a missing provider. The shared report-cell candidate has
114 passing focused frontend cases across seven files, a fresh build, and
separate full frontend/browser replays below.
The synthetic fixture now uses the canonical Matter-code normalizer rather
than guessing case preservation. No legal authority, provider result or model
answer quality is fabricated by these fixtures.

The original d2a adapter was executed from a separate pinned read-only baseline
worktree. The new Watch reproduction failed in its call phase at the exact
missing retained-summary assertion, after all captures/reviews succeeded.
The candidate's three complete report modules passed 19 cases/57 phases,
including nine new access/lifecycle/source/1,001-record bound cases. Neither
this SQLite result nor a source patch certifies PostgreSQL or production.

Run05 passed all eight intended journeys after a fresh build, including both
positive Watch report/review/reload widths. Run06 then passed all ten intended
journeys in six files: it also verifies table-cell DOCX redlines at both widths,
original source download hashes, the actual parse response, visible inserted
and deleted text, persisted source reload and retirement of only the synthetic
contract. These tests do not close full structural Word comparison/edit/export.
Both API and browser requests retain the no-paid marker.

The complete frontend run01 retained 2,722 passes and six failures. Four were
independent exact-inventory expectations, one a UUID run label, and one an
actual Windows symlink-privilege refusal in a security fixture. Correct the
source integration and portable fixture rather than removing the guard: use
the canonical visible run-ID format and prove a real dangling junction on
Windows (the unchanged file symlink on Linux). Full replacement02 passed all
2,728 cases without failures or skips. Native JSON/XML/console failure receipts
are preserved; early standalone preflights reused the default Playwright output
directory, so not every old DOM snapshot survives. Subsequent runs must use
unique native output directories as well as unique report filenames.
Fourteen PostgreSQL counterparts now use the connection-disabled migrated
template fixture and are discovered; none is relabelled as a local pass before
execution. No native/mobile tooling or MacBook workflow was modified.

## Release And Reviewer Gates

Claude owns the preceding release closeout and must independently review this
candidate. The first separate read-only Claude review could not authenticate:
its OAuth session expired before any model call; this is not reviewer approval.
No credentials were requested in chat and no alternate credential or broader
permission is substituted. The owner has been asked to sign in normally.

Required before closure: complete intended browser fixture/inventory, focused
built-Docker journeys, full canonical Docker and CI/security, protected main,
guarded exact-SHA deployment, production replay, required maintenance/resume
and honest workbook update. No source candidate, prior-release QA or green
unit component bypasses those gates. MacBook app work stays separate.
