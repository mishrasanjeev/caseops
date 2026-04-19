# CaseOps Cybersecurity Review

Date: 2026-04-19

## Scope

This review covered:

- API code in `apps/api`
- web app code in `apps/web`
- deployment/config in `infra` and `docker-compose.yml`
- existing security-focused tests
- dependency CVE checks for Python and Node production dependencies

Validation performed during this review:

- `uv run pytest tests/test_webhook_security.py tests/test_tenant_isolation.py tests/test_session_revocation.py tests/test_rate_limiting.py tests/test_password_policy.py tests/test_security_settings.py tests/test_file_security.py tests/test_ethical_walls.py tests/test_audit_coverage.py` -> `66 passed`
- `npm audit --workspace @caseops/web --omit=dev --json` -> no known production vulnerabilities
- `pip-audit -r .tmp/api-requirements-audit.txt -f json` -> no known Python dependency vulnerabilities

## Executive Summary

The codebase has a decent baseline on tenant isolation, webhook signature validation, password policy, session revocation, and file-type screening. The highest-risk gaps are elsewhere:

1. unsafe archive extraction in corpus ingest
2. explicit TLS verification disablement for live court sync
3. deployment env classification bug that weakens non-local security guards
4. tenant AI policy exists in schema but is not enforced
5. browser session architecture is fragile because bearer tokens live in `localStorage`
6. uploaded-document parsing is not malware-scanned or isolated, and the user-upload OCR path ignores configured safety limits

## Findings

### 1. High - Unsafe tar extraction in corpus ingest allows path traversal and link-based escapes

Evidence:

- `apps/api/src/caseops_api/services/corpus_ingest.py:850`
- `apps/api/src/caseops_api/services/corpus_ingest.py:855`
- `apps/api/src/caseops_api/services/corpus_ingest.py:857`
- `apps/api/src/caseops_api/services/corpus_ingest.py:860`

Why this is a security bug:

- `_safe_extract_tar()` validates members, but then calls `tf.extractall(dest)` on the entire archive anyway.
- The traversal check uses string prefix matching on resolved paths: `str(target).startswith(str(resolved_root))`.
- That check is unsafe for sibling-prefix cases such as `C:\extract` vs `C:\extract-evil`.
- Symlink and hardlink members are only skipped during validation, not removed from extraction. `extractall()` still extracts them.

Impact:

- A malicious tarball can write outside the intended extraction directory.
- Symlink or hardlink members can be used to overwrite or expose files outside the ingest root.
- This is especially sensitive because the ingest path handles externally sourced legal corpus archives.

Remediation:

- Replace `extractall()` with per-member extraction after explicit allow/deny decisions.
- Reject absolute paths, `..` traversal, symlinks, and hardlinks before extraction.
- Use `Path.is_relative_to()` or `os.path.commonpath()` style checks instead of string-prefix checks.

### 2. High - Live court sync explicitly disables TLS verification on connection failure

Evidence:

- `apps/api/src/caseops_api/services/court_sync_sources.py:217`
- `apps/api/src/caseops_api/services/court_sync_sources.py:226`
- `apps/api/src/caseops_api/services/court_sync_sources.py:232`
- `apps/api/src/caseops_api/services/court_sync_sources.py:241`

Why this is a security bug:

- `_fetch_text()` and `_fetch_bytes()` retry with `verify=False` for hosts in `TLS_RETRY_HOSTS`.
- That converts a connection problem into an authenticated data-trust bypass.

Impact:

- A man-in-the-middle can tamper with cause lists, orders, and PDFs ingested from those court sources.
- The system can import falsified court data into matter workspaces and downstream AI outputs.

Remediation:

- Remove the `verify=False` fallback.
- If specific court sites have broken chains, pin or trust the needed CA/intermediate instead.
- Fail closed and surface a retriable operational error rather than silently trusting unverifiable TLS.

### 3. High - The Cloud Run deployment profile bypasses non-local security validators

Evidence:

- `infra/cloudrun/api-service.yaml:31`
- `apps/api/src/caseops_api/core/settings.py:7`
- `apps/api/src/caseops_api/core/settings.py:118`
- `apps/api/src/caseops_api/core/settings.py:127`
- `apps/api/src/caseops_api/tests/test_security_settings.py:16`

Why this is a security bug:

- Cloud Run sets `CASEOPS_ENV=cloud`.
- The settings layer only treats `staging`, `production`, and `prod` as non-local.
- As a result, the placeholder JWT secret guard and local-only CORS augmentation logic are skipped in the actual deployed env profile.

Impact:

- A misconfigured cloud deploy can boot with the placeholder auth secret without triggering validation.
- The cloud profile is also treated like local for CORS augmentation logic.
- Existing tests only cover `staging|production|prod`, so this deployed path is unguarded by tests as well.

Remediation:

- Treat `cloud` as non-local, or invert the logic to explicitly whitelist local/dev/test only.
- Add tests for the deployed env name used in `infra/cloudrun/api-service.yaml`.

### 4. High - Tenant AI policy controls are defined but not enforced

Evidence:

- `apps/api/src/caseops_api/services/tenant_ai_policy.py:3`
- `apps/api/src/caseops_api/services/tenant_ai_policy.py:9`
- `apps/api/src/caseops_api/services/tenant_ai_policy.py:63`
- `apps/api/src/caseops_api/services/tenant_ai_policy.py:94`

Why this is a security bug:

- The file itself says enforcement of `max_tokens_per_session` and `external_share_requires_approval` is scaffolded but not wired.
- During this review, the only references to `resolve_tenant_policy` and `is_model_allowed` in `apps/api/src/caseops_api` were inside `tenant_ai_policy.py` itself.

Impact:

- Tenant-level AI governance can be bypassed entirely.
- Model allowlists, token budgets, and external-share approval controls are not currently dependable as security controls.
- This matters for confidentiality, cost control, and enterprise policy claims.

Remediation:

- Enforce policy in provider selection, generation entrypoints, export/share paths, and model-run accounting.
- Add tests that prove denied models, exceeded token budgets, and unapproved external-share attempts fail closed.

### 5. Medium - Browser bearer tokens are stored in `localStorage`

Evidence:

- `apps/web/lib/session.ts:5`
- `apps/web/lib/session.ts:22`
- `apps/web/lib/session.ts:31`
- `apps/web/lib/session.ts:47`
- `apps/web/lib/session.ts:48`

Why this is a security bug:

- Session bearer tokens are readable from JavaScript.
- Any successful XSS, compromised third-party script, or malicious browser extension can exfiltrate the token directly.

Impact:

- A single browser-side script execution bug becomes full session theft.
- Because the token is a bearer token, possession is enough to impersonate the user until expiry or revocation.

Remediation:

- Move session secrets to `HttpOnly`, `Secure`, `SameSite` cookies.
- Add server-managed refresh and rotation if long-lived sessions are needed.
- At minimum, pair the current design with strong CSP and token binding/short TTLs.

### 6. Medium - The web app ships without standard browser hardening headers

Evidence:

- `apps/web/next.config.ts:1`
- `apps/web/next.config.ts:8`

Why this is a security bug:

- The Next config defines redirects only; there is no `headers()` block adding CSP, HSTS, `X-Frame-Options` or `frame-ancestors`, `Referrer-Policy`, or `Permissions-Policy`.
- With tokens in `localStorage`, the lack of CSP is especially important because there is no strong browser-side containment if an XSS sink appears later.

Impact:

- Higher blast radius for any future XSS.
- Clickjacking protection is absent.
- Referrer and feature exposure defaults are left looser than they should be for a legal product.

Remediation:

- Add a strict `Content-Security-Policy`.
- Add HSTS for production, clickjacking controls, `Referrer-Policy`, and `Permissions-Policy`.

### 7. Medium - Untrusted document parsing is not isolated, and the upload OCR path ignores configured safety limits

Evidence:

- `apps/api/src/caseops_api/api/routes/matters.py:383`
- `apps/api/src/caseops_api/api/routes/contracts.py:190`
- `apps/api/src/caseops_api/services/document_jobs.py:251`
- `apps/api/src/caseops_api/services/document_processing.py:89`
- `apps/api/src/caseops_api/services/document_processing.py:97`
- `apps/api/src/caseops_api/services/document_processing.py:101`
- `apps/api/src/caseops_api/core/settings.py:105`
- `apps/api/src/caseops_api/services/ocr.py:154`
- `apps/api/src/caseops_api/services/ocr.py:157`

Why this is a security bug:

- Upload routes schedule `run_document_processing_job` via FastAPI background tasks, so untrusted file parsing can execute inside the API service process.
- The user-upload scanned-PDF path in `document_processing.py` loops over every page and writes temporary rendered images, but does not enforce `ocr_max_pages`.
- A safer bounded OCR path exists in `services/ocr.py`, but the upload pipeline does not use it.

Impact:

- Large or adversarial scanned PDFs can drive CPU, memory, and temp-disk exhaustion.
- Parser-bug blast radius is larger because parsing is not isolated from the API service boundary.

Remediation:

- Remove in-process background parsing from the API service.
- Force all untrusted document parsing into an isolated worker or sandbox.
- Reuse the bounded OCR path and enforce page, DPI, timeout, and temp-space limits for uploads.

### 8. Medium - Uploaded documents are parsed before any malware scanning or quarantine step

Evidence:

- `apps/api/src/caseops_api/services/file_security.py:1`
- `apps/api/src/caseops_api/services/file_security.py:16`

Why this is a security bug:

- The upload screening only checks extension, content-type coherence, and magic bytes.
- The file itself explicitly states that full virus/vendor scanning is not part of this step.
- The same upload then flows into PDF, DOCX, OCR, and image parsers.

Impact:

- Weaponized legal documents reach parser code directly.
- The system lacks a quarantine stage for malicious or suspicious uploads.

Remediation:

- Add AV scanning and quarantine before extraction/indexing.
- Refuse parsing until the scanner returns clean.
- Keep parser workloads in a separate trust boundary even after scanning.

### 9. Low - API docs are enabled by default, and the public metadata route leaks deployment information

Evidence:

- `apps/api/src/caseops_api/core/settings.py:23`
- `apps/api/src/caseops_api/main.py:33`
- `apps/api/src/caseops_api/main.py:35`
- `apps/api/src/caseops_api/api/routes/meta.py:14`
- `apps/api/src/caseops_api/api/routes/meta.py:15`

Why this is a security bug:

- API docs are opt-out, not opt-in.
- The public `/meta` route returns environment and app URL information.

Impact:

- Accidental exposure in a non-local environment increases reconnaissance value for attackers.

Remediation:

- Default docs off outside explicit dev/test modes.
- Strip environment detail from public metadata or gate it behind auth.

### 10. Low - Public demo request endpoint logs user PII and has no anti-automation controls

Evidence:

- `apps/web/app/api/demo-request/route.ts:14`
- `apps/web/app/api/demo-request/route.ts:37`

Why this is a security bug:

- The route accepts public POSTs and logs name, email, company, and role directly to server logs.
- There is no CAPTCHA, rate limit, or abuse throttle on this route.

Impact:

- Unnecessary PII lands in logs.
- The endpoint can be spammed for log-noise or minor resource abuse.

Remediation:

- Stop logging raw PII.
- Add bot protection and rate limiting for the public form.

### 11. Low - Rate limiting is narrow and keyed only by raw remote address

Evidence:

- `apps/api/src/caseops_api/core/rate_limit.py:10`
- `apps/api/src/caseops_api/core/rate_limit.py:11`
- `apps/api/src/caseops_api/api/routes/auth.py:17`
- `apps/api/src/caseops_api/api/routes/bootstrap.py:19`

Why this is a security bug:

- Only login and bootstrap are rate-limited.
- The limiter key uses `get_remote_address` directly, with no proxy-aware trust model in the app.

Impact:

- Protection is weaker behind reverse-proxy topologies.
- Other public or abuse-sensitive endpoints do not inherit baseline throttling.

Remediation:

- Make the limiter proxy-aware for the deployed ingress model.
- Add throttles to other public or abuse-prone endpoints.

## What Checked Out

The following areas looked materially better:

- tenant isolation on core matter surfaces
- webhook signature validation and idempotency
- session revocation
- password policy enforcement
- basic upload file-type validation
- audit coverage on many material mutations

Existing security-focused API tests passed:

- `test_webhook_security.py`
- `test_tenant_isolation.py`
- `test_session_revocation.py`
- `test_rate_limiting.py`
- `test_password_policy.py`
- `test_security_settings.py`
- `test_file_security.py`
- `test_ethical_walls.py`
- `test_audit_coverage.py`

Supply-chain result:

- no known production Node vulnerabilities from `npm audit` during this review
- no known Python dependency vulnerabilities from `pip-audit` during this review

## Priority Fix Order

1. Fix tar extraction in `corpus_ingest.py`.
2. Remove `verify=False` court-sync fallback.
3. Fix env classification so deployed profiles are treated as non-local.
4. Wire tenant AI policy into real generation and sharing paths.
5. Move auth away from `localStorage` and add browser security headers.
6. Isolate document parsing, enforce OCR caps, and add malware scanning.
