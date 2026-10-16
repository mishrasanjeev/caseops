# Exact-Release Production Verification Budget Recovery

## Scope And Current Truth

This is an operational acceptance correction for ARCH-OPS-23/QG-SEC-004 and
the release gates serving J04/M03, J08/M08 and UJ-18, not a change to legal
records or application workflows. PR539 merged as
`599defc31471ab4e532afcbd855ebaf6963fc8d5`, tree
`51c4eb12423254aa620dc46aad79d2c22e36c75a`. API00493-9hp and web00470-trk
serve that release at100% latest untagged traffic. Its full Docker acceptance
and fresh main CI/Security/CodeQL passed. The candidate in this document is not
yet merged, deployed or production-certified.

## Reproduction And Root Causes

Production workflow38888165664, tester job116930996232, started10:35:08UTC
and completed11:13:52UTC on October16. GitHub's actual failure annotation says
the job exceeded its38-minute maximum. Its native completion, discovery,
JUnit and journal nevertheless reconcile all115 intended cases:102 pass,
13 explicit skip,zero failure/retry. Native execution consumed2,277.991s;
summed case durations were2,190.780s. Test-step success is not whole-job success.

The previous partition removed indexing and dated October13/15 work but still
left the whole September05 catalogue inventory in the core partition. These
18 cases account for759.286s of this run. The other97 cases account for
1,431.494s. These measured sums inform the split, but are not replacement
runtime or production acceptance evidence. Preserve the cancelled run and all
earlier failed/incomplete releases.

The same rollout also reproduced an independent initial-maturity defect.
The committed worker activation immediately queried a just-retired revision
using a monitoring end-time of now minus120s. That end-time preceded retirement,
so `fetch_counts` rejected the interval before the bounded positive-sample
polling could run. The original deployment ended1 after routing; a separate,
source-bound exact canonical tail later obtained real stop proof and completed
successfully. That continuation did not erase the original failure or repeat
the consumed test-legal manual-IP grant.

## Corrections And Adjacent Boundaries

- Derive complementary core and catalogue selections from complete canonical
  discovery, preserving native project and test IDs. Required union is the
  original163 identities:97 core,18 catalogue,6 indexing and42 dated cases.
- Keep mutation-capable jobs serialized, one browser worker, retries0 and the
  existing38-minute job limit. Require each partition's source-bound native
  artifact and the exact disjoint union before certification.
- A newer workflow graph must not execute an unsupported partition after
  checking out an older serving release. Reject missing release-owned support
  rather than silently selecting all tests or omitting the new gate.
- Wait for an initially non-queryable mature interval only inside the existing
  total stop-proof budget. Continue checking already-mature revisions. Future
  retirement timestamps fail before credentials or waiting.
- Require the same two aligned mature active/idle zero samples; missing,
  truncated or positive counts remain unproved. Transport/auth/envelope failures
  still stop immediately, with no retry or absence-as-zero interpretation.

No legal-source eligibility, application test body, Matter lifecycle, private
generation fence, provider-cost rule, tenant policy or entitlement changes.
GBA remains read-only. External legal/source/consent gaps and the unidentified
historical reopening report remain open.

## Verification And Release Ownership

The full initial worker-stop module has33 scoped native passes, including
five new maturity/future/deadline cases and a mixed-cohort regression. These
are development results, not fresh whole-candidate or production acceptance.
Production workflow/evidence regression modules own partition selection,
missing/duplicate identities, required artifacts and release-version guards.

Fresh amended-source native/Docker/CI gates, canonical main merge, guarded
exact-SHA production deployment and the complete live inventory are still
required. A failed job must remain failed in the history; do not waive the
job outcome because its cases passed. Private-projection cadence remains
paused until successful exact-release QA and two later clean serial runs from
the immutable API image, with zero rebuilds in the second run.

Actual dated evidence and both workbook verdicts are retained under the local
`outputs/calendar-ip-20261013` release evidence directory. A future final
receipt, not this candidate checkpoint, owns closure and the deployed SHA.
