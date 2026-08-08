# IPLF-022A production attachment-scan hotfix evidence — 8 August 2026

## Status and truthful boundary

This document records a production acceptance failure found while releasing
IPLF-022A and the repository-controlled hotfix candidate that followed it.
The failed production run is not represented as a pass. At the time this file
was first committed, the hotfix still required independent PR CI/Security/
CodeQL, merge to canonical `main`, exact-revision production deployment, and a
fresh run of the same dated production Playwright workflow.

Overall IP-program status remains `PROGRAM INCOMPLETE`. This repair changes no
legal decision, filing, fee, provider permission, client communication, or
human approval. All production acceptance data described below came from the
synthetic `caseops-qa` tenant.

## Released candidate and production evidence

- Canonical merge: `c04f456d53dbd891b6696b8d30cf260bc7999543`.
- Pull request: `#182`.
- Fully green PR CI run: `31257880237`, including all eight API coverage
  shards, aggregate coverage, web typecheck/tests/build, and Playwright.
- Security run: `31257880239`, passed.
- CodeQL run: `31257880243`, passed.
- API image digest:
  `sha256:35fa4aff73e4d8240e68ba12a40251991defa293f66f4094d00dfce97204e81b`.
- Web image digest:
  `sha256:236a3a374d38ef7d5aaf6055bc4d03d1c3a13ff493bda7e3f14a023a3c22422e`.
- Migration execution: `caseops-migrate-job-jhm99`, successful in 12.49
  seconds, including migration `20260807_0003`.
- API revision: `caseops-api-00251-rz9`, 100% traffic.
- Web revision: `caseops-web-00231-rjc`, 100% traffic.
- Independent HTTPS verifier result: exact full release SHA, API revision, and
  web revision matched.
- All six recurring Cloud Run jobs were reconciled to the exact immutable API
  digest and their expected Scheduler identity, schedule, timezone, and
  enabled state.
- ClamAV remained required and fail-closed. The live sidecar used port 3310
  with `failureThreshold=120`, `periodSeconds=2`, and `timeoutSeconds=1`.

## Production acceptance failure

Production workflow `31259105432` checked out and verified the exact serving
release. Its complete dated RAM batch passed. The final Notice-module suite
then failed at `tests/e2e/notice-module-prod.spec.ts:130` while waiting up to 90
seconds for the reply-document attachment response.

The failure was not a missing selector or a request that never reached the
API. Cloud Run request logs for the synthetic Matter
`f39e7949-1915-4f5d-9db6-e1fe7fc6b97b` show:

| Request | Result | Production latency | Serving revision |
| --- | --- | ---: | --- |
| Primary received-notice attachment | HTTP 200 | 0.481949619 s | `caseops-api-00251-rz9` |
| Reply-document attachment | HTTP 200 | 246.103970758 s | `caseops-api-00251-rz9` |

The slow request trace was
`projects/perfect-period-305406/traces/f04c08829ff7b3565752c0c9add7058d`.
It ran on an already-ready instance that had served normal requests
immediately beforehand, so a stale build and a ClamAV sidecar startup wait
were excluded. The response completed only after the browser's 90-second
acceptance window had expired.

## Root cause and repair

Every affected upload writer used the following synchronous storage order:

1. materialize the request stream to a local temporary file;
2. upload that file to GCS and delete the temporary file;
3. call `resolve_storage_path` on the new storage key;
4. perform a GCS existence check and download the same object into the local
   cache;
5. scan the downloaded copy with ClamAV; and
6. only then return the upload response.

This made successful response latency depend on an unnecessary immediate GCS
read-after-write round trip before malware acceptance. The hotfix introduces
the optional `validate_temp_file` persistence hook and invokes the required
ClamAV check on the exact temporary bytes before any local move or GCS upload.
The temporary file is always removed in the persistence `finally` block.

The same invariant is applied to every repository owner that previously did a
post-persistence virus scan:

- Matter attachments, including Notice received/reply/sent documents;
- contract attachments;
- inbound-email imported attachments;
- standalone CompanyNotice files; and
- outside-counsel portal work-product uploads.

Security is strengthened rather than bypassed: infected content or an
unavailable required scanner fails before durable storage, no rejected GCS
blob needs best-effort cleanup, the scanner sees the exact bytes whose digest
and size are later persisted, and production `CASEOPS_CLAMAV_REQUIRED`
semantics are unchanged.

## Local verification

Focused static and storage/security regression:

```text
python -m ruff check <six changed services> test_document_storage.py
All checks passed

python -m pytest test_document_storage.py test_virus_scan.py -q
17 passed, 1 warning
```

The added GCS regressions prove that validation sees the complete temporary
file while no remote object exists, successful validation precedes upload,
the temporary file is removed afterward, and a rejected validation leaves the
fake GCS object set empty.

Widened upload-owner and lifecycle regression:

```text
python -m pytest \
  test_company_profile_and_matters.py \
  test_contracts.py \
  test_communications.py \
  test_notices.py \
  test_portal_outside_counsel.py \
  test_storage_governance.py \
  test_legalworkspace_document_lifecycle.py -q

112 passed, 3521 warnings in 462.60s
```

Warnings were the existing Starlette TestClient and SQLite datetime adapter
deprecations; there were no skips, retries, quarantines, or allowed failures.

## Release and rollback requirements

The candidate is acceptable for merge only after full independent PR gates
pass. Release must then build the exact canonical-main revision, deploy both
immutable images, run migrations, pin all recurring jobs, verify exact API/web
serving identity over HTTPS, and rerun production workflow
`Prod verification (Playwright)` so both the dated RAM batch and Notice-module
suite pass.

Rollback is the normal previous-revision traffic rollback. No schema change is
introduced by this hotfix. If rollback is required, uploads remain fail-closed
but regain the old GCS round trip; the failed latency evidence must not be
erased or relabeled as healthy.
