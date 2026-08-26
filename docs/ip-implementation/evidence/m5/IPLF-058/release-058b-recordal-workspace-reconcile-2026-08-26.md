# IPLF-058B recordal workspace correction: exact-release evidence

**Date:** 2026-08-26

**State:** `deployment_verified` correction to the existing IPLF-058B release.
IPLF-058B, its eight allocated UJ-36/UJ-61 paths, and parent IPLF-058 remain
implemented, verified, and deployment-verified. Independent provider,
legal-SME, and law-firm UAT remain external acceptance.

## Release identity

| Item | Exact evidence |
| --- | --- |
| Correction PR | #356 |
| Canonical main | `3ce3e93e7ee07161c396344e0fe24d7a162216c2` |
| API build | Cloud Build `fafeda37-fd68-4ab6-903f-8e7414884655` |
| Web build | Cloud Build `e3edbb8a-738a-4c2f-bcfc-cfd85475b057` |
| API image | `sha256:63dec6751cc2a4dc49c94fd0035c3a68009804ef4e9e4cf288d4af33d0234a8fd` |
| Web image | `sha256:eff611a80dca0c5e64de68358aa3aad98510e8f557b45db5037801b1129b2ebba` |
| Migration | `caseops-migrate-job-qv5m4`, completed before service traffic moved |
| API release | `caseops-api-00365-gqq`, 100% latest-only traffic |
| Web release | `caseops-web-00344-hkp`, 100% latest-only traffic |
| Exact-main CI | GitHub Actions `32948328688`, passed |
| Security | GitHub Actions `32948328731`, passed |
| CodeQL | GitHub Actions `32948328672`, passed |
| Production verifier | GitHub Actions `32948328870`, passed |
| Health | `GET https://api.caseops.ai/api/health` returned `{"status":"ok"}` |

The release was built from a clean exact-main worktree. Alembic completed before
traffic moved, all eight recurring jobs reconciled to the immutable API digest,
the superseded case-tracking scheduler remained paused, and the judge-mapping
and authority-metadata jobs retained their governed paused states. Stale
revision tags were cleared, service-level warm capacity remained configured,
and independent release identity verification returned the full expected SHA
and both serving revision names.

## Production acceptance

| Gate | Result |
| --- | --- |
| Complete RAM/IP batch | 87 passed, 4 documented conditional skips, 21.4 minutes |
| IPLF-058B responsive correction | Passed within the RAM batch at 360px and desktop |
| IPLF-027B A0 quiescence | 1 passed in 31.7 seconds |
| Notice production module | 2 passed in 20.2 seconds |

The separately governed IPLF-037B renewal acceptance did not run because none
of its four approved production fixture IDs is configured. That explicit
activation gate is unrelated to IPLF-058B and was not counted as a hidden
failure.

## Corrected behavior

The selected recordal now uses one bounded workspace response for the recordal,
title interests, transaction history, accessible docket, selected-docket
documents, Registry workspaces, and deadline workspace. The four detail tabs
mount from the selected list row while that aggregate is pending. Corpus-wide
docket and document catalogues remain lazy and appear only in workflows that
need them.

Production acceptance proved that all four tabs are visible and fit at a
360-pixel viewport before awaiting the aggregate, exactly one aggregate request
is made, and the page does not fan out duplicate selected-docket, document,
Registry, or deadline requests. This removes the prior concurrency-one queue
amplification without adding another recordal, docket, document, Registry, or
deadline owner.

## Boundary

The correction changes no schema, legal state machine, filing behavior,
provider activation, payment behavior, or external recipient. It preserves the
IPLF-058A recordal owner, IPLF-039E title-interest ledger, canonical docket and
document owners, Registry workspace, and shared deadline service. IPLF-060B
remains the next repository slice; this record makes no JUDGE or UJ-20 claim.
