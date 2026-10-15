# Production acceptance capacity correction

Status: Partially fixed. QG-SEC-004 exact-release verification; local workflow
and evidence-consumer controls only. Fresh joined CI, Docker, canonical release
and complete deployed acceptance are still required. No production mutation,
verification rerun or release claim is part of this change.

## Observed failures

The tester job in production verification `38660900422` ended with 119 native
test-end records (102 passed, 13 skipped, 4 failed), two unended October 12
cases, and no October 13 invocation. The next run, `38693611994`, retained 120
test-end records (106 passed, 13 skipped, 1 failed), an unended October 12
mobile case and again no October 13 invocation. Both exhausted the existing
38-minute job envelope. Passing early cases cannot certify the absent cases.

The latter run's Intelligent Review failure is separate from capacity. An old
document job `0741dc82-35e9-479a-ba31-b62adad55f69`, queued at
`2026-10-15T01:43:22.450235Z`, completed at `06:42:26.040413Z` and emitted the
source-change event that advanced the tenant tombstone epoch from 9572 to 9573.
It was not the current bootstrap or a preceding test. The saved Review's
same-generation manifest correctly failed closed. This patch does not change
private authorization, manifest semantics, document processing or queue policy;
the separately owned pre-QA quiescence work must preserve those boundaries.

## Permanent capacity boundary

The original six suites remain. `tester-prod-chromium` now discovers 115 cases;
the four October 10 indexing and two October 12 Contract AI cases move intact
to `tester-index-prod-chromium`; six October 13 Calendar/IP cases remain in
`test-legal-write-prod-chromium` but execute in their own final job.

The dependency chain is the original six-suite matrix, then `tester-index`,
then `test-legal-write-oct13`. Later partitions may execute after an ordinary
predecessor failure, not after workflow cancellation. Every job retains
38 minutes, one worker, zero retries, release-owned checkout, no-paid headers,
native incremental evidence, JUnit and always-uploaded failure artifacts.
Other original invocations and opt-in exclusions are unchanged.

Each of the three tester invocations independently retains the unfiltered,
release-config-bound canonical discovery before executing its selected subset.
The certification consumer requires all three complete hashed envelopes, equal
canonical inventories, exact ordered selections and a unique exact union.
Mandatory indexing/AI and October 13 cases must each pass once: skipped,
unended, failed or retried mandatory cases cannot admit certification. The
public-claims evidence write is downstream of this check and all suite jobs.

## Scoped verification

Evidence: `outputs/calendar-ip-20261013/prod-capacity-partition-20261015-01`.

- Actual installed Playwright discovery: 115 + 6 + 6 = 127 unique cases;
  all three ordered selections agree with unfiltered discovery. Discovery only,
  not browser execution or a production acceptance result.
- Initial full two-module offline replacement: 192 passed, 576 ordered phases,
  zero failures/errors/skips; exact collection and JUnit identities; natural
  exit zero and unchanged owned-source/dependency pins.
- The retained first full run is 179 passed / 1 static assertion failure: YAML
  anchor expansion exposed three copies of a conditional step. The replacement
  assertion identifies the sole eligible matrix while preserving all original
  credential, source-age and release-owned code assertions.
- New negative controls cover dropped/overlapping/reordered/altered identities,
  missing or executed canonical discovery, missing partition receipts, source
  drift, retries, skipped/failed/unended mandatory outcomes and increased workers.

No prior failed production run is overwritten or upgraded by these local checks.

## Intended-inventory and private-resume follow-up

Independent review found that agreement between two truncated inventories was
not sufficient. The consumer now requires the reviewed exact counts 115/6/6
and unique file/title/repeat semantics, not merely nonempty core selection and
matching native IDs. An omitted core case in both discovery and selection,
extra/duplicate cases, semantic duplicates under new native IDs and rerouting
all fail closed. Legitimate future inventory changes require explicit review.

Actual offline discovery of immutable main `0c82fbb008b524cd8ad75df0a445edaeabc1199d`
resolved its original tester121 + October13_6. The new115 +6 +6 selection has
the exact same127 semantic file/full-title/repeat identities one-to-one, after
accounting for the project-role change, with no missing, extra or duplicates.
The baseline's234-file import closure and two statically read data/fixture files
come from that exact Git object; installed Node/Playwright dependencies were
reused read-only, not installed or rewritten. The first attempt's module-
resolution/missing-static-file failures remain retained as setup failures.

`scheduler_inventory.py` independently requires `Prod Playwright (tester-index)`
and `Prod Playwright (test-legal-write-oct13)` to succeed before private cadence
can resume. A success-labelled evidence-recording job cannot compensate for
either missing, failed, cancelled or skipped partition.

Follow-up evidence:
`outputs/calendar-ip-20261013/prod-capacity-intended-inventory-followup-01`.
The final four complete offline modules pass292 cases /876 ordered phases,
zero skips/errors/failures, with exact collection/JUnit and unchanged scoped
source pins. The original ten new RED failures plus one later semantic-duplicate
RED are retained; the intermediate291-pass run is historical, not final proof.
The earlier192-pass seal is unchanged and does not cover these later amendments.
