# Intelligent Review history latency, 2026-09-27: root cause and fix

Source: production verification run
[36291638337](https://github.com/mishrasanjeev/caseops/actions/runs/36291638337)
for release `1c617a318ef1eaa2113d6547407466e19db4000f` (API revision
`caseops-api-00471-n4q`, project `perfect-period-305406`, region `asia-south1`).

## Symptom

`tests/e2e/iplf-063b-intelligent-review-2026-08-28-prod.spec.ts:140` failed at
line 498. After "Refresh reviews", the review detail never showed `abstained`
inside the 10-second expectation. The page's first
`GET /api/research/reviews?limit=50` took **32.4 s** (request log
2026-09-27T03:35:05Z). The same request took 39.02 s on 2026-09-25T03:51:56Z
(revision `caseops-api-00463-2qp`). Warm, it took 1.3-4.0 s: 43 requests since
2026-09-20, p50 2.38 s, p90 4.00 s, 177,595 bytes for 50 reviews.

## Root cause

There were two defects. Each one made the other worse.

### 1. The page opened with more concurrent reads than warm capacity

`caseops-api` serves one request per instance (`containerConcurrency: 1`)
and keeps four instances warm. At 03:35:05.82-.85Z the review page started five
reads at once:

| Read | Instance | Latency |
| --- | --- | --- |
| `GET /api/authorities/research-reports` | `...3a757e3d33` (warm) | 0.058 s |
| `GET /api/matters/?limit=100` | `...a7c4f1de65` (warm) | 0.113 s |
| `GET /api/ip/portfolio?limit=100` | `...e069bfbafa` (warm) | 0.474 s |
| `GET /api/research/reviews/{id}` | `...e38fc0bc60` (warm) | 0.072 s |
| `GET /api/research/reviews?limit=50` | `...cb36ed7d02` (**new**) | **32.417 s** |

Cloud Run started two new instances in that second and kept the fifth read on
`cb36ed7d02`, which first served at 03:35:36.7Z. It stayed there even though
the other new instance was ready at 03:35:24.5Z and all four warm instances
were free within 0.5 s. The detail read in that burst duplicated the history
response, which already carries every complete record. It had been restored
on 2026-09-22 (`b3a93225`) so that a slow history read could not stall a
deep link. The duplicate treated the second defect's symptom and added a
fifth request.

### 2. The history reauthorized each review's private manifest separately

`list_intelligent_reviews` called `private_saved_source_manifest_is_current`
once per row. Each call issued its own queries: active generation, saved
projections, saved generation, active rows after a rebuild, the team-scoping
flag with ACL-authorized IDs, and the team-scoping flag with current source
versions. That is about seven statements per review, and it explains the
1.3-4.0 s warm baseline.

### Why the tests missed it

- `test_intelligent_review_list_query_count_is_constant_at_page_size`
  seeded reviews with no private source manifest. The per-row check returned
  before issuing a query, so the test passed at three statements. Every
  production review carries a manifest from the private capture path.
- The page test "loads a deep-linked review without waiting for bounded
  history" required the duplicate detail read.

## Cold start: where the time goes

Production, 343 instance starts between 2026-09-20 and 2026-09-27 (264
autoscaling, 79 minimum-instance or deploy replacements). Seconds are measured
after Cloud Run's "Starting new instance" event:

| Phase | p50 | p90 | max |
| --- | --- | --- | --- |
| ClamAV container started | 1.9 | 2.4 | 3.6 |
| ClamAV signatures loaded | 13.9 | 17.6 | 22.4 |
| ClamAV listening on 3310 | 18.4 | 24.0 | 28.4 |
| API imports finished | 20.5 | 26.3 | 31.6 |
| API application constructed (+2.6 s p50) | 22.7 | 29.2 | 35.3 |
| API reranker warm-up done (+5.6 s p50) | 28.6 | 36.3 | 44.5 |
| API startup probe succeeded (serving) | 28.6 | 37.0 | 46.3 |

The API's own startup was the critical path in **332 of 343** starts. ClamAV
finished last in 11. Startup CPU boost is already enabled, so these figures
include it.

A local diagnostic used the exact production digests (API
`sha256:298f8d12...`, ClamAV `mirror.gcr.io/clamav/clamav@sha256:90382d8f...`)
with production limits (API 2 CPU / 4 GiB, ClamAV 1 CPU / 1500 MiB), on an
isolated internal network, three runs each:

| Scenario | Scanner PONG | API serving | API imports | Reranker |
| --- | --- | --- | --- | --- |
| Production topology (both start together, fence on) | 12.6-16.0 s | 12.9-16.4 s | 7.0-9.2 s | 4.4-4.8 s |
| Scanner fence disabled (diagnostic only) | n/a | 11.9-14.6 s | 5.5-8.4 s | 4.2-4.6 s |
| `--check-hash-based-pycs never` (diagnostic only) | 13.2-15.6 s | 13.6-16.0 s | 6.8-8.4 s | 4.6-4.9 s |

The scanner therefore adds at most 1-2 s locally. In production, API imports
take 20.5 s at p50, against 7-9 s locally. That gap is the cold filesystem of
a 2.08 GB image on a new Cloud Run instance. The local runs disable
`freshclam` and have no Internet access, like the project's cold-start
harness. In production, `freshclam` downloads and tests the daily database on
ClamAV's single vCPU while clamd loads, which accounts for part of the
18.4 s.

Nothing here weakens malware readiness. The lifespan fence still keeps the API
socket closed until clamd answers PONG, and every upload is still scanned.
This change does not touch startup, so the cold-start harness
(`scripts/verify-api-cold-start.ps1`, PowerShell 7) is not part of its
acceptance.

## Fix

- `private_saved_source_manifests_are_current` makes one decision for many
  manifests. Each manifest keeps its own result. Only the lookups are shared,
  and each shared lookup is a per-row predicate over a union of identifiers.
  `private_saved_source_manifest_is_current` is now the same function
  called with one manifest, so every caller keeps a single policy.
- `list_intelligent_reviews` reauthorizes the whole page in one statement
  set: 12 statements for a non-owner member, whatever the page size.
- On first load the review page starts only the history and the frozen
  reports. Matters load after the reports and IP dockets when the IP tab
  opens. The page reads a single review only when it is outside the bounded
  history or still generating.
- CORS preflights may be cached for 7,200 s, Chromium's maximum. Starlette's
  default is 600 s. Browser `GET`s from the web client send only `Accept` and
  are not preflighted. Mutations and automation-marked requests are.

## Verification

- `tests/test_20260927_review_history_bounded.py` (SQLite) and its PostgreSQL
  wrapper cover 41 reviews. Every review carries a captured private manifest,
  saved in the active generation or in a generation retired by an unrelated
  rebuild. The set includes reviews whose Matter access was revoked in
  either generation, a duplicated projection, an unknown generation and a
  changed hash. Each batched decision equals that manifest's own decision
  and its stated expectation. A 5-review page and a 41-review page both
  take 12 statements.
- Reproduction on the unfixed commit `328761c5`, in a separate checkout whose
  imported module was verified: 273 statements for the same page.
- `test_review_history_page_of_100_is_bounded_at_production_private_index_volume`
  (PostgreSQL) uses 100 reviews and adds 10,000 unrelated projections to each
  of two generations. It runs with no manual `ANALYZE`, a 1,500 ms
  per-statement budget, and hash and merge joins disabled. On the same local
  dataset the per-row algorithm took 703 statements and 3.9-4.7 s; the
  batched page takes 12 statements and 0.21-0.29 s.
- Two new page tests fail against the previous page: a deep link waits for
  the bounded history, and first load keeps at most two reads in flight.
- In a real browser, `tests/e2e/support/review-page-reads.ts` records the
  page's API reads from navigation until it settles. The Docker review
  journey and the exact-release production journey both require: at most two
  reads in flight, no single-review read for a review the history returned,
  and no IP portfolio read before the IP tab opens. Against the previous page,
  the same Docker journey failed with four reads in flight (reports, Matters,
  IP portfolio, history); a deep link adds the detail read as a fifth.
- Docker acceptance and exact-release production verification are recorded
  on the pull request.

## Warm capacity: options for the owner

Prices are official Cloud Run list prices, retrieved 2026-09-27. `asia-south1`
is a Tier 1 region. `caseops-api` uses request-based billing, so warm idle
instances are billed at the idle rate: $0.0000025 per vCPU-second and
$0.0000025 per GiB-second. Figures assume 730 hours a month, before the free
tier and committed-use discounts. One API instance is 3 vCPU and 5.5 GiB (API
plus ClamAV sidecar), so each warm instance costs about **$55.85 a month**
idle. Billable instance time over the last 30 days averaged 3.93
instance-equivalents, so the four warm instances account for nearly all billed
instance time: about $223 a month at the idle rate, plus the active CPU rate
($0.000024 per vCPU-second) while requests run.

| Option | Monthly change | Effect |
| --- | --- | --- |
| Keep service minimum 4 (recommended with this change) | $0 | The review page now keeps at most two reads in flight on first load. |
| Service minimum 6 | about +$112 | Absorbs a five-read page beside one other user without a cold start. |
| Service minimum 8 | about +$223 | Headroom for several concurrent users of multi-read pages. |
| Startup CPU boost | already on (about $4 a month) | Already included in the p50 28.6 s above. |
| One-year Cloud Run commitment | about -17% on committed usage | Pricing only; latency is unchanged. |

Longer-term levers, each needing its own acceptance:

- Allow more than one request per API instance. This removes fan-out as a
  cold-start trigger but is blocked by the 2026-06-08 event-loop incident.
- Shrink the API image (for example, move OCR language packs to the worker
  image) to cut the 20.5 s production import time. The cold-start harness
  must then prove clean and EICAR scans and scanner outage and recovery.
- Move scanning to a shared service. This saves about $16 a month of sidecar
  idle cost per warm instance but changes the fail-closed topology, and the
  sidecar is not on the critical path today.
