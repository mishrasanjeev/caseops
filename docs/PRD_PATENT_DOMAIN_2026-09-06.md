# CaseOps Patent Domain Contract

Version: PAT-2026-09-10.2. Owner: Codex. Status: execution contract, not a
claim of delivered patent functionality. Parent: IP platform PRD PAT-01..04,
IP-SCOPE-01..10; UJ-29, UJ-39, UJ-40, shared title/licensing UJ-60/61.

## 1. Scope And Current Truth

September 10 proceeding increment: the versioned child contract
`PRD_PATENT_PREGRANT_PROCEEDING_2026-09-10.md` owns UJ-39-EXC-03. It adds a
concrete source-pinned pre-grant opposition journey on the canonical proceeding
identity and patent application docket. It does not promote the entire patent
domain or close the remaining proceeding/obligation/title paths. Verification
belongs to the new proceeding handoff; the prior 28-file handoff is immutable.

Implement invention disclosure, independent patent applications and family
relationships, parties and priorities, prosecution and separate opposition
proceedings, immutable document/claim versions, sourced obligations, instruction,
filing and acceptance, title/licensing and Matter links, audit and reporting.
India is the first authoritative jurisdiction. PCT and foreign applications may
be recorded as sourced facts; this does not enable foreign deadline calculation,
office connectivity, fee calculation, filing or legal-completion claims.

Historical baseline at main 6a85cd5 plus the September 05 candidate, before
the patent implementation below:

- IpAsset, IpDocketRecord, documents, sources, grants, legal rules, deadlines,
  cost links, lifecycle and audit owners exist. Do not create alternatives.
- IpAssetCreateRequest only permits trademark. There is no patent application,
  family or patent prosecution API or page.
- IpDocketRecordResponse requires TrademarkParticularVersionRecord. Its
  serializer raises when particulars are absent. Patent records cannot be added
  to that legacy listing without a typed compatibility boundary.
- Private projection candidates currently include every active IP docket's
  title. Restricted membership access alone does not meet the separate
  unpublished-invention discovery restriction.
- Trademark event-to-phase mappings and trademark application foreign keys
  cannot be used as patent application/proceeding identities.

Current local implementation: restricted family disclosure intake now has a
tenant-composite migration, canonical docket/asset ownership, idempotent create,
versioned corrections and history, exact document-version/hash pins, scoped
document upload/download, and dedicated index/detail pages. The dated
IPLF-080A Playwright journey passes at 393px and 1280px on fresh Docker images,
including reload, stale-write denial, cross-tenant denial and terminal closure.
The public catalogue may describe this as intake only, never complete patent
management or authoritative automation. Family intake does not imply application,
party/priority graph, prosecution or maintenance implementation.

General disclosure filters now exclude patent anchors and linked documents
before discovery/pagination. The shared access command rejects removal of a
patent anchor's restriction. Authorized internal downloads and shared lifecycle
commands remain usable. Version rows are append-only through the service and
migration-installed PostgreSQL/SQLite update/delete guards. Direct mutation and
refused-downgrade regressions must keep proving the retained evidence is intact.
Exact test results and earlier failures are retained in
`ip-implementation/codex-takeover-2026-09-06.md`; no production acceptance is claimed.

## 2. Canonical Ownership

| Concern | Decision | Owner and boundary |
| --- | --- | --- |
| Patent legal facts | NEW typed domain | Family, application, priority, party, prosecution, claim set, proceeding and obligation detail; no trademark status or form aliases |
| Record access/lifecycle | EXTEND | IpDocketRecord anchors and existing grants/walls; terminal and optimistic-concurrency fences remain authoritative |
| Asset identity | EXTEND | IpAsset with a patent-specific validated writer; no trademark particulars row as a placeholder |
| Documents | LINK | Existing IpDocument/IpDocumentVersion and scoped links; patent packages pin immutable version IDs and hashes |
| Parties | EXTEND | Existing IpPartyAndRole identities with immutable patent source/address/supersession details; no second party-name owner and no inferred access or title grant |
| Source provenance | LINK | Existing source-record owner; record publisher, exact version, URL/hash and effective dates |
| Legal rules/deadlines | EXTEND | Existing IpRuleVersion and IpDeadline with right_kind=patent and exact jurisdiction/office match |
| Calendar/tasks/reminders | LINK | Existing shared owners through their typed IP-target adapters; one operational row per obligation |
| Money | LINK | Existing cost item, estimate/actual and billing lineage. No second paid balance or invoice state |
| Title/licensing | LINK | Existing dated title interests and contractual obligations; source and active reference revalidation |
| Litigation | LINK | Existing IpMatterLink with access and lifecycle independent on both sides |
| Audit/idempotency | EXTEND | Existing audit, command-idempotency and outbox owners; no patent-only delivery queue |
| Domain claims | EXTEND | IPLF-079 server catalogue and authenticated machine evidence; no tenant/admin self-promotion |

All new child references require company-composite foreign keys, appropriate
leading-column indexes, bounded pagination and source-preserving migrations.
No client, creator, office or tenant identifier is invented by the browser.

## 3. Records And Invariants

### Family And Disclosure

A family has its own ID, title, client scope, disclosure date, confidentiality,
creator, status and version. Applications are independent legal records linked
to a family; adding, moving or correcting a relationship never merges or
renumbers them. A family may contain different jurisdictions and offices.
Disclosure narratives and unpublished material are restricted by default.

Each application records application kind (provisional, complete, convention,
PCT international, national phase, divisional, patent of addition), jurisdiction,
office, raw published application/publication/grant identifiers, filing and
publication dates, current prosecution phase, source and version. Identifier
normalization is bounded and preserves source strings. Office plus jurisdiction
plus identifier kind scope duplicate detection; duplicates require reconciliation.

Priority and parent links have their own dated, sourced identities. Reject
self-links, cycles, cross-tenant parents, impossible chronology and conflicting
parent/application kinds. A possible priority or inventorship discrepancy is
visible for legal review, not silently corrected by AI.

### Parties And Ownership

Inventors, applicants, proprietors, agents and licensees have separate roles,
effective ranges, source references and address/country snapshots. Changes
supersede dated facts without overwriting filed historical parties. A party name
does not grant access. Recordal and contractual execution are distinct events.

### Prosecution And Proceedings

Application phases are patent-specific: disclosure, filing preparation, filed,
published, examination requested, examination, response filed, hearing, granted,
refused, withdrawn, abandoned and closed. Do not infer state from a document
filename, payment status or text extraction. Exceptional transitions require an
explicit sourced event; neither import nor worker may reopen a terminal anchor.

Events include filing/publication, examination request, FER/office action,
response, hearing, amendment, grant/refusal, appeal linkage and restoration.
Every event pins received/effective dates, application version, source evidence,
actor, reason and the document versions actually filed. Siblings do not receive
the event through family membership alone. Backdated correction is append-only
and presents downstream recalculation impact before changing any open obligation.

Pre-grant opposition, post-grant opposition, revocation and compulsory-licence
proceedings have distinct IDs, side, forum/office, source number, stage and audit.
They are not application phases and do not reuse trademark opposition stages.
An absent provider number is explicitly pending allocation, not fabricated.

### Document And Claim History

Claim sets, specification, drawings, abstract, sequence listing, translation,
amendment and response documents pin immutable IpDocumentVersion IDs and hashes.
A version records its predecessor, kind, source and prepared/filed/granted role.
Reject cyclic lineage, mismatched tenant/application, a missing predecessor and
silent replacement of a filed/granted version. Filing packages bind a manifest
of exact versions; later edits create a new package and cannot change old receipts.

### Obligations And Completion

Annuity, examination, response, working statement, restoration and other
obligations have independent identity, period, jurisdiction, source/rule version,
trigger date, due date, status and instruction/funding/filing/acceptance evidence.
Unverified dates can be retained as manual pending-confirmation facts; automatic
calculation requires a currently active patent rule and source pack.

States distinguish proposed, confirmed, instructed, funded, paid/filed, accepted,
overdue, grace/restoration, superseded and cancelled. Payment is never acceptance.
Receipt acceptance verifies the exact application, obligation period and source;
only then may the next obligation be proposed idempotently. Changed fee/entity,
void or superseded costs invalidate dependent quotes and require replacement.
Historical obligations retain their original rules, amounts and receipts.

## 4. User Journeys And Tests

| Journey/test prefix | Normal path | Required exception paths |
| --- | --- | --- |
| UJ-29 / IPLF-080-FAMILY | Create restricted disclosure; record parties; add first application; add sourced priority and family members; reload graph; filter and report | Inventor/title conflict; distinct applications sharing a family; jurisdiction mismatch; priority cycle; duplicate identity; cross-tenant relation; revoked access; terminal parent; stale command |
| UJ-39 / IPLF-080-PROSECUTION | Open application; record office action and source; pin response versions; propose verified deadline; record instruction; file exact package; attach acknowledgement; record sourced next state | No sibling propagation; amended claims immutable; separate opposition identity; ambiguous source pending confirmation; missing/wrong receipt; unavailable rule; source withdrawn; backdated impact; stale application; terminal and revoked access |
| UJ-40 / IPLF-080-MAINTENANCE | Propose annuity/working period; confirm source/rule/entity; link quote; record instruction and funds; file/pay; reconcile receipt; accept; propose next period once | Fee/entity change; void/superseded cost; payment without acceptance; duplicate receipt; wrong period; lapse/restoration separate; not-applicable declaration source; stale rule; obsolete instruction; no duplicate next period |
| UJ-60/61 / IPLF-080-TITLE | Link dated title interest/licence; pin executed contract and recordal evidence; reconcile related obligation | Cross-tenant contract; expired/void evidence; encumbrance conflict; historical ownership retained; legal recordal not inferred from payment |
| IPLF-080-DOCUMENTS | Upload validated document; attach exact version; prepare package; file; compare amendment; reload immutable history | Wrong MIME/malware; inaccessible version; foreign application version; superseded package; duplicate upload; concurrent new version |
| IPLF-080-ACCESS | Creator opens restricted disclosure; explicit colleague grant; revoke; verify direct and discovery denial | Owner/admin search is not automatic invention-discovery permission; portal/export/AI exclusion; ethical wall; expired grant; cache invalidation |
| IPLF-080-COMPAT | Existing trademark list, create, opposition, documents, billing, reporting and lifecycle still work beside patent anchors | Patent anchor sent to legacy trademark mutation must fail before writing; no fake particulars; no trademark deadline or status accepted |
| IPLF-080-IMPORT | Original source preview; classify valid/invalid/duplicate; confirm valid rows; reload outcomes; replay | Invalid row reserves no identity; source and relationships revalidated at commit; partial recovery preserves created rows; no normalized-source substitution |

For every normal and exception path test the API contract, persistence/reload,
audit outcome and user-visible behavior. Desktop, tablet and narrow mobile must
show all required actions without collision or collapsed controls. Never call a
schema-only fixture a completed journey.

## 5. Security, Concurrency And Work Bounds

- Every application, family, proceeding, version and obligation is tenant scoped.
  All mutations reauthorize under the canonical parent lock and require an
  expected version. No generic metadata write can change lifecycle state.
- Existing Company-first projection fencing and canonical parent lock order
  remain unchanged. Multiple scope parents are locked in deterministic order.
- Unpublished invention records and linked documents are excluded from general
  portfolio, assistant discovery, vector retrieval, portal publication and bulk
  export until their specific permitted sharing path is implemented and tested.
  A generic admin role is not a blanket publication grant.
- Model/provider calls never hold database transactions or lifecycle locks.
  Regular suites and QA tenants make no paid provider calls.
- List endpoints use cursors and maximum 100 rows; workspace child sections
  paginate independently. Family graph traversal is cycle-safe with a bounded
  node count and explicit has-more indication, never silent truncation.
- Test at least 10,000 applications, 1,000 family members and 500 document
  versions. Count queries and prove a concurrent unrelated mutation remains
  responsive. Do not satisfy performance by increasing timeouts.

## 6. Source And Legal Rule Gates

Source discovery on 2026-09-06 identified the official
[Patents Act publication](https://www.ipindia.gov.in/acts/patent-act-1970),
[forms and fees](https://www.ipindia.gov.in/patents-before-you-apply-forms-official-fees),
and [manuals publication](https://www.ipindia.gov.in/resource/patents-resources-manuals).
The Act page describes its e-version as updated through 1 August 2024; the
manuals listing includes a 2026 draft. Neither a page's recent crawl timestamp
nor a draft manual proves an operative rule version.

Before activating any calculation, create the existing source/rule records with
exact official text/document hash, effective dates, amendment provenance,
jurisdiction and issuing authority. The machine-executed fixture pack must cover
the actual applicable rule version and boundary dates. This contract deliberately
does not hardcode legal durations, fees or filing-form applicability from memory.

Source failure cannot erase last verified facts. A new amendment invalidates
affected future calculations for review but does not rewrite confirmed historical
obligations. Keep operational UI and manual evidence capture usable while only
the unsupported automatic/legal-completion capability remains disabled.

## 7. Concrete Implementation Milestones

1. P0 Compatibility: versioned contract; typed patent DTOs; domain catalogue;
   explicit legacy-route and invention-discovery guards. No patent mutation
   enabled until compatibility and tenant-isolation tests pass.
2. P1 Family intake: source-preserving migration; family/application/party/priority
   CRUD and graph; restricted access; reload, duplicates, source correction,
   cycle prevention, terminal/stale writes and desktop/mobile browser journeys.
3. P2 Prosecution: immutable versions/packages; office actions; separate
   proceedings; source-pinned events; shared task/deadline adapters; complete
   UJ-39 and no trademark semantic leakage.
4. P3 Maintenance/title: obligation periods and rule selection; instruction,
   cost and filing/acceptance lineage; next-period idempotence; complete
   UJ-40/60/61 and cost supersession regressions.
5. P4 Import/reports/security: original-source preview/commit/recovery, bounded
   family reports, exports/portal sharing where supported, access revocation,
   performance and all shared-owner regressions.
6. P5 Local release: clean workstation Docker migration/rollback, PostgreSQL,
   API, frontend and Playwright; every skip accounted for; updated docs and
   public claims; no paid API use by automated tests.
7. P6 Activation: exact-main deployment and complete dated production evidence.
   Source/legal fixture failures keep the affected automation and beta/GA claim
   closed; they do not prevent completing independently testable implementation.

September 09 prosecution continuation: the isolated patent track implements
source-pinned immutable document editions/filing manifests and manually sourced
prosecution events with concurrency, impact preview and explicit exceptional
transition acknowledgement. This is a P2 vertical, not completion of P2-P6 or
IPLF-079/080. Separate proceedings, obligation/instruction/cost/acceptance/title
lineages, imports, complete reports and integrated release proof remain open.
See `ip-implementation/evidence/patent-closure-2026-09-09.md` for exact proof.

September 08 reconciliation: family, application, party, priority and bounded
graph implementations are already present on baseline `5145fb3a`. Their dated
production-shaped tests are existing regression coverage, not new work to
rebuild. Full UJ-29 acceptance and P2-P6 remain open, including prosecution,
proceedings, claim/package versions, obligations, title, import and integrated
release proof. See `ip-implementation/catalogue-ip-completion-2026-09-08.md`.

Historical September 07 milestone checkpoint: P1 in progress. The family-disclosure vertical has local
Docker acceptance. Independent source-pinned application persistence, identifier
corrections, immutable history and scoped UI now exist and are undergoing local
Docker acceptance. The application checkpoint subsequently passed all 155
PostgreSQL tests and seven complete patent browser journeys on the source-pinned
September 07 Docker images; see the takeover evidence for exact identities and
the corrected locator replay. Parties, priorities, graph and complete P1
acceptance remain pending. P2-P6 are not complete. The implementation must not
promote beta/GA or automate legal deadlines from this limited intake evidence.

### P1 Application Execution Detail

Continue UJ-29 / PAT-01 / IPLF-080-FAMILY and IPLF-080-COMPAT through the
existing docket, asset, document, lifecycle, access and idempotency owners.
Applications have independent docket/asset identities; family membership never
copies a lifecycle event or access grant to a sibling. Initial application facts
do not constitute a prosecution event, official filing or registry activation.

Store append-only application versions and identifier-source rows. A separate
current-identity projection enforces tenant/jurisdiction/office/kind/normalized
value uniqueness; corrections retain the prior raw facts and release only that
application's superseded current reservations. Normalization folds Unicode case
and whitespace without discarding punctuation or the original source string.
Persist full scope alongside a bounded hash key and reject a hash collision.
Every source pins an authorized exact document version and hash. Unsupported
registry-snapshot admission remains explicit until its real workflow exists.

Application acceptance must prove two independent applications in a family,
pending-to-final identifiers, correction/history/reload, same-office duplicates,
different-office isolation, concurrent conflicting admission, source hash/ACL
failure, terminal/stale rejection, unchanged family/trademark history, and
393/768/1280px browser operation. Data-map, OpenAPI, page tests, legal-source
pickers, 10,000-record query bounds and migration refusal are part of the same
delivery. These requirements are implementation work, not an acceptance claim.

### P1 Party Execution Detail

Extend canonical IpPartyAndRole rows with a one-to-one immutable patent detail
that binds exact source version/hash, address snapshot, actor, reason and a
docket-scoped sequence. Supersession creates another canonical party and detail;
it never updates a filed historical party or rewrites its effective range.
The current view excludes superseded facts; the history view retains their
original dates and sources. This evidence is not a legal ownership/recordal
decision and never grants access or propagates a party to family members.

Commands compare the observed anchor facts/lifecycle and party-collection
sequence under the existing parent lock. A stale collection fails with 409.
The source, optional active client and superseded party must resolve in the
current tenant and same docket. Exact duplicate current facts, a second
supersession, inaccessible evidence and terminal targets fail closed. A source
linked to a closed sibling remains historical evidence under the existing
read-only-source exception; no mutation of that sibling is permitted.

Both family and application work areas offer bounded current/history pages,
source download, add and sourced replacement. Page continuation pins the
collection sequence so a concurrent change requires a fresh first page.
Acceptance includes all five roles, address/country snapshots, date validation,
immutable database guards on both canonical and detail rows, tenant/source
revocation, stale writes, disposal overlap, idempotent replay, indexed pagination,
and desktop/tablet/mobile reload journeys. Existing trademark parties and
opposition workflows must remain unchanged. This continuation is not yet done.

### P2 Work Product And Prosecution Contract

An application owns an independently incrementing work sequence, checked with
the current application-facts and lifecycle versions under its canonical parent
lock. New editions retain the same lineage identity and append one immutable
manifest of at most 20 exact authorized document versions. The source, version,
hash, actor, reason, original title and application anchor cannot be rewritten.
A filed event pins the exact edition, so a later amendment never rewrites a
previously filed package. A lineage admits at most 1,000 retained editions;
reads paginate at most 100 editions and load their source rows in batches.

Prosecution is distinct from docket lifecycle and generic trademark events.
Manual filing, publication, examination request, office action, response,
hearing, amendment and grant records require source evidence and a current
impact preview. Filing requires a frozen package. An exceptional phase change
requires a reason and acknowledgement; a backdated event previews at most 100
open deadlines and requires acknowledgement without changing those deadlines.
Preview identity includes the locked work sequence and current deadline facts.
No filing receipt alone asserts registry acceptance or legal completion.

Current authorization is rechecked on both retained reads and idempotent
replays. Closing an application preserves authorized byte-identical source
download but rejects every ordinary write and creation replay. Explicit reopen
does not reactivate older editions or replay a prior lifecycle command. A new
root in the reopened epoch requires explicit creation. A second closure on the
same day remains a distinct lifecycle operation.

The domain catalogue also requires an implemented end-to-end workflow contract
and distinct examination/response/annuity/working/restoration legal-source
fixture checks before patent beta/GA admission. A signed all-green intake-only
checklist cannot bypass missing workflow implementation. None of these manual
records activates deadline calculations, paid providers, AI, portal sharing or
automatic notifications for unpublished patent material.
