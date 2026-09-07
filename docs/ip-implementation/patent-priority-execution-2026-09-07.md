# Patent Priority Execution

Owner: Codex. Status: implementation brief, not delivered functionality.
UJ-29 / PAT-01 / IPLF-080-FAMILY / IPLF-080-COMPAT; modules M02, M08, M13 and M14.
The current locally tested family/application/party checkpoint is recorded in
`evidence/local-patent-parties-2026-09-07.md`. IPLF-080A/B remain in progress.

## Existing Owners

The parent IP PRD assigns priority and divisional relationships to
`ip_relationships`. Its source/target dockets, relationship kind and effective
date are the canonical legal identity. Do not add a competing patent edge
table with another relationship identity. Madrid's existing relationship
writer and behavior must remain unchanged.

`PatentPriorityCreateRequest`, `PatentPriorityRecord` and
`PatentFamilyGraphResponse` already exist as unimplemented contracts. Extend
them instead of adding parallel DTOs. Application facts and identifiers retain
their existing owners; family membership does not merge records or grant access.

## Evidence And Corrections

Extend IpRelationship with append-only patent evidence versions. Each version
has its own ID, canonical relationship ID, tenant/source/target docket lineage,
monotonic sequence, exact child/parent fact and lifecycle versions, document
version/hash, actor, reason and creation time. A source correction may reuse
the same immutable canonical relationship identity while adding a new evidence
version. A changed parent/kind/date uses the corresponding canonical identity.

Supersession links are tenant- and source-application scoped and cannot fork.
Withdrawal is an explicitly sourced correction to the recorded link, not a
patent abandonment or application lifecycle change. It preserves the original
record and is excluded from the current graph. No generic PATCH or DELETE is
introduced. Database guards retain both the evidence and the canonical patent
relationship; existing non-patent relationship operations remain available.

Requests compare child and parent versions, both lifecycle versions and the
source application's observed priority collection sequence. Replays resolve
the saved result under current access. A source pin is not legal verification;
the current implementation accepts accessible uploaded evidence and must reject
unimplemented registry-source activation truthfully.

## Writer And Validation Boundary

Reuse the tenant-scoped patent application identity writer fence before actor,
idempotency, document or docket locks. Pair-only locks cannot prevent disjoint
concurrent additions from completing a cycle. Lock source/target dockets and
source-document parents in the existing deterministic order, and recheck all
preconditions after acquiring them. New links reject closed child or parent
targets. A source-only correction or withdrawal of an existing unchanged
relationship may read a closed parent as a historical reference; the child
must remain active. Changing the parent/kind/date again requires an active
new parent. Historical reads remain possible under current access.

Reject self-links, cross-tenant or inaccessible targets, duplicate current
relationships, cycles, known impossible chronological ordering and relation
names inconsistent with the recorded application kinds. Missing facts or a
possible substantive legal discrepancy must not be silently repaired by AI.
Do not invent foreign-office law, priority entitlement, deadlines or fee rules.
Cross-family links must not silently move or merge either application.

Office and jurisdiction discrepancies are retained as immutable review flags,
not guessed office-name rejection rules. The source records currently contain
office labels, not verified, versioned office identities. Missing filing dates
and a priority date preceding the named parent's filing date also remain visible
for review. These flags do not certify or deny priority entitlement.
The official [Indian Rule 4](https://www.ipindia.gov.in/acts/patent-rules-2003/rule-4)
distinguishes the divisional filing-office rule from transfers and historical
applications; plain string equality cannot establish compliance with that rule.
[Section 54](https://ipindia.gov.in/acts/patent-act-1970/section-54) distinguishes
addition filing/grant conditions from merely recording a parent link.
The [WIPO national-phase description](https://www.wipo.int/en/web/pct-system/national-phase)
supports the PCT-international parent type; it is not a source for automatic
foreign deadlines or national grant status.

Application corrections share this same fence and revalidate their current
incoming and outgoing relationships before changing facts. A correction cannot
invalidate an existing relationship's chronology or kind constraints. A closed
historical counterpart is a read-only reference during that validation, not a
new mutation target or an automatic reopening.

## Reads And User Journey

1. Open an accessible patent application and its priority work area. Initial
   discovery must complete before editing; errors do not look like an empty list.
2. Select the parent from the server's accessible application catalog. Record
   the relationship, sourced date and exact evidence version; show stale/source
   errors without client-invented identifiers or a mutation retry.
3. Save, inspect the returned record and reload. Both applications retain their
   original identities, families, access, facts and lifecycle state.
4. Replace a source or correct/withdraw a link explicitly. Show immutable
   history, its reason and the byte-hash-verified source download.
5. Open the family graph. Applications and relationships paginate independently
   with the existing 100-node and 500-relationship response caps and explicit
   continuation indicators. Do not describe a partial page as the whole family.
   An off-page or cross-family endpoint is not an orphan or missing patent.
6. Follow a linked application, then return. Revoked source/record access must
   fail closed on direct reads, lists, graph, history and replay without leaking
   private titles or counts. Closing a record never resurrects old links.

## Required Regression Evidence

| ID | Required proof |
| --- | --- |
| IPLF-080-PRIO-01 | Create, persist, exact source/hash download and idempotent replay |
| IPLF-080-PRIO-02 | Same canonical fact with corrected source retains immutable history |
| IPLF-080-PRIO-03 | Parent/kind/date correction and explicit withdrawal retain predecessors |
| IPLF-080-PRIO-04 | Duplicate, self-link, cycle and concurrent disjoint-cycle denial |
| IPLF-080-PRIO-05 | Cross-tenant, revoked parent/source, foreign history and replay denial |
| IPLF-080-PRIO-06 | Stale child/parent/collection and terminal target rejection |
| IPLF-080-PRIO-07 | Chronology/kind changes cannot invalidate incoming/outgoing links |
| IPLF-080-PRIO-08 | Cross-family link preserves independent families, grants and lifecycle |
| IPLF-080-PRIO-09 | Current/history pages, independent graph cursors and explicit bounds |
| IPLF-080-PRIO-10 | PostgreSQL tenant FKs, immutable rows, retained downgrade refusal and interrupted index recovery |
| IPLF-080-PRIO-11 | At least 10,000 applications and 1,000 family members; bounded rows/queries and responsive unrelated writer |
| IPLF-080-PRIO-12 | Complete 393/768/1280px browser journeys plus breakpoint control visibility |
| IPLF-080-PRIO-13 | Existing Madrid/trademark relationships and law-firm regressions remain green |
| IPLF-080-PRIO-14 | Data map, OpenAPI/frontend schemas, product guide, docs and accurate public claims |
| IPLF-080-PRIO-15 | Bound ancestry by retained rows and SQL calls, including dense graphs and superseded history; prove below-bound admission, over-bound HTTP rejection/replay, unchanged evidence and a responsive concurrent writer |

The release follow-up replaces the recursive ancestor query with a tenant-scoped
batched walk: at most 1,000 distinct ancestors, 2,000 retained relationship versions
plus one overflow sentinel, and 32 batch reads of at most 100 source dockets.
Superseded and withdrawn versions consume the row budget before current-edge
filtering. One separate indexed read captures the tenant sequence. Oversized
requests fail closed with `patent_priority_graph_bound`; no timeout, access fence,
immutable history or canonical relationship owner is weakened. Six boundary
PostgreSQL/HTTP cases, 145 affected offline API checks and the fresh b525
three-width priority journeys pass. The evidence record retains the original
negative reproductions and fixture failures. This is local implementation
proof, not a production-ready verdict or full patent completion.

Run all implementation tests on a new local Docker candidate. Preserve the c351
tester environment and immutable reports. Do not commit, publish or deploy
based on this brief, schema existence or fixture-only quality scores. The
existing BUG-010 and whole-program release gates remain open.
