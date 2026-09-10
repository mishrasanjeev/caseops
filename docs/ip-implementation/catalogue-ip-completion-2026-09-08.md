# Catalogue, IP Programme And Cold-Start Completion

Owner: Codex. Baseline: `5145fb3a4b51b26af116220ff10a7389bde6324d`.
Status: implementation in progress; not a release certificate.

## Acceptance Contract

The September 08 request supersedes the five-Act release boundary. BUG-010
must cover every existing catalogue Act, all provisions in its authoritative
edition, and the schedules, Orders and annexures previously excluded. Relevant
IP Acts and subordinate source packs must also support their domain journeys.
An invented heading, secondary commentary, a guessed source URL, an omitted
identity or a disabled empty option cannot satisfy completeness. Published
repealed provisions and disputed/current-law applicability require explicit
historical or withheld treatment, never fabricated operative law.

Separate document acquisition, extraction reconciliation, source admission,
current-law applicability and user-visible verification. Every source needs a
publisher, issuing body, edition/cutoff, retrieval time, immutable document and
text hashes, and exact provision locator. Compare the whole publisher inventory,
not just the old seed's incomplete counts. Preserve prior attached evidence.

## Work Tracks

| Track | PRD mapping | Concrete acceptance |
| --- | --- | --- |
| CAT-1 Source inventory | J05/J07/M05, MOD-TS-017, US-046A-D, IPLF-006 | Reconcile all 23 existing Act identities to authoritative publishers; inventory full sections/articles, schedules/Orders, amendments and successor-law relationships |
| CAT-2 Complete data | F-TS-1..4, F-T095, RAM05-STATUTES | Reproducible extraction of every source unit, no missing/duplicate boundaries; exact provenance; preserve historical references; no secondary commentary promoted as law |
| CAT-3 Usable catalogue | Same | Whole-data API checks; browser search, selection, attachment, source opening and persisted reload for every Act at mobile/tablet/desktop; missing/retired/conflicted units remain explicitly reconciled |
| PERF-1 Cold start | EG performance controls, IPLF-070/100 | Profile image import, route construction, reranker and scanner separately; eliminate redundant work; retain offline assets and fail-closed scan; measure cold and warm Docker HTTP workloads and production latency |
| IP-1 Foundations | IPLF-027B, 028A/B, 029A/B | Complete existing canonical governance, ownership, reconciliation and evidence contracts without duplicate owners or destructive preflight bypasses |
| IP-2 Trademark integration | IPLF-039G/H | Reconcile remaining normal/exception journeys against already implemented 039A-F; implement only genuinely absent behavior |
| IP-3 Patent | IPLF-079A/B, 080A/B; PAT-01..04, UJ-29/39/40 | Complete prosecution, separate proceedings, exact claim/document versions, obligations, instructions, filing/acceptance, title, import and reporting using existing anchors |
| IP-4 Data and operations | IPLF-070A/B, 071A/B, 072A/B, 073A/B | Scoped export/purge/holds, restore with worker fences, measured recovery, access reviews and expiring emergency access; real PostgreSQL and isolated Docker drills |
| IP-5 Other domains | IPLF-090A/B, 091A/B | Versioned child contracts and distinct design/copyright/domain/licensing/enforcement/GI/plant-variety/layout/trade-secret/customs workflows; no trademark discriminator substitution |
| IP-6 Integrated release | IPLF-100A/B | Cross-IP migration/reporting/client operations/security, complete local regression, canonical main/CI, exact production release and dated E2E |

## Baseline Reconciliation

- Manifest has 144 slices: 119 implemented, 10 in progress, 15 not started.
  All 25 unfinished IDs appear once in the tracks above. An implemented status
  is not automatically an executed verification or legal/provider acceptance.
- Existing catalogue has 23 Acts and 4,336 rows after the release seed: 1,632
  verified, 2,704 other rows. Five editions have 1,689 source identities,
  comprising 1,631 selectable, 56 retired and two quarantined. Constitution
  Article 14 is the other verified row. These are baseline counts, not targets
  that may suppress inserted provisions or schedules.
- The old seed has incorrect or reused India Code handles, including BSA,
  Hindu Marriage, Consumer Protection, RTI and Prevention of Corruption.
  Source identity must be verified from publisher metadata, not retained blindly.
- Production's 53.1926-second portfolio request spent about 51.69 seconds before
  API startup completed. It is not evidence that this request's SQL took 53s.
- Read-only local profile of baseline API image at 2 CPU/4 GiB, no network:
  import under cProfile 17.700s; 3.309s in compile, 2,554 route constructions.
  Instrumented timing is diagnostic, not a user-visible latency benchmark.
- Local Docker is shared with Routerwise. Do not prune global Docker state,
  stop unrelated services, or discard retained CaseOps test data.

## Verification And Release Order

1. Add failing regressions for observed defects and inventory omissions.
2. Implement bounded changes with API/schema/UI parity and source-history safety.
3. Build fresh workstation Docker images. Migrate independent PostgreSQL test
   databases; restore exact-image catalogue seeds before browser acceptance.
4. Run complete API/PostgreSQL/frontend/browser gates with structured per-test
   reconciliation. Exercise all affected normal, error, stale-write, lifecycle,
   access-revocation, tenant isolation, idempotency and scale boundaries.
5. Update PRD, strict ledgers, Product Guide, public claims and release documents
   to actual evidence. Never turn absent source/legal proof into a passing flag.
6. Only after local acceptance: publish/merge current canonical candidate, verify
   CI, use canonical deployment, prove exact serving identities, rerun dated
   production E2E and require clean private maintenance after test writes stop.

Automated tests remain offline/deterministic and send the no-paid-provider
marker. Any live paid probe is a separate explicitly bounded operational action.
