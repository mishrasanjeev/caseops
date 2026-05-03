# Brutal Review Fixes README - 2026-05-03

Branch: `codex-brutal-hardening-review`

This README records the concrete fixes made during the repo-wide brutal review
pass. It is intentionally scoped to defects that were substantiated in code or
tool output during this pass, not broad product-roadmap gaps that need weeks of
feature work.

## Review Scope

- Mapped the monorepo with `rg --files` and inspected the FastAPI, Next.js,
  upload/storage, auth, CSRF, webhook, OCR, and security-header surfaces.
- Ran baseline and targeted verification across backend lint/tests, frontend
  typecheck/tests/build, dependency audits, secret/risky-code searches, and
  package compatibility checks.
- Rechecked prior audit items in `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`
  and `docs/CYBERSECURITY_REVIEW_2026-04-19.md` against current code before
  selecting fixes.

## Fixes

### 1. GCS Upload Quarantine Cleanup

Problem: upload routes persisted the file, then scanned the stored bytes. If
ClamAV rejected the upload, cleanup called `resolve_storage_path(...).unlink()`.
That removed the local materialized file but left the already-uploaded GCS blob
behind.

Fix:
- Added `delete_stored_document(storage_key)` in
  `apps/api/src/caseops_api/services/document_storage.py`.
- Wired matter, contract, and outside-counsel upload cleanup paths to delete both
  local cache files and remote GCS blobs.
- Added regression coverage proving GCS blob and cache deletion.

### 2. Storage Path Segment Hardening

Problem: persisted storage keys were assembled from dynamic IDs without an
explicit segment validator. The current callers normally pass UUID-like IDs, but
storage code should fail closed at its own boundary.

Fix:
- Added strict storage segment validation for company, namespace, workspace, and
  attachment path parts.
- Added local target containment validation before replacing temp uploads.
- Added regression coverage for unsafe path segments.

### 3. Atomic GCS Cache Materialization

Problem: a failed GCS download could leave a partial cache file; later reads
would return that partial file because the cache path existed.

Fix:
- GCS downloads now write to a same-directory temp file and atomically replace
  the cache path only after a successful download.
- Failed downloads delete the temp file.

### 4. DOCX And Text Upload Hardening

Problem: `.docx` validation accepted any ZIP-shaped file with `PK` magic bytes,
including renamed ZIPs and unsafe internal paths. Plain text uploads also
accepted NUL bytes.

Fix:
- DOCX uploads now must be readable ZIP containers with `[Content_Types].xml`
  and `word/document.xml`.
- DOCX internal paths reject absolute paths, traversal, Windows drive-like
  prefixes, and excessive entry counts or expansion size.
- `.txt` uploads reject NUL bytes.
- Added regression tests for valid DOCX, renamed ZIPs, DOCX traversal, and text
  NUL bytes.

### 5. Bounded PDF OCR In Upload Processing

Problem: the upload document-processing fallback rendered every PDF page with a
hardcoded scale, bypassing configured `CASEOPS_OCR_MAX_PAGES`,
`CASEOPS_OCR_RENDER_DPI`, provider selection, and page-quality gates.

Fix:
- Routed scanned-PDF fallback through `services.ocr.ocr_pdf()`, which enforces
  configured page caps, DPI, provider selection, truncation telemetry, and
  page-quality filtering.
- Added regression tests for successful bounded OCR and empty/truncated OCR
  diagnostics.

### 6. Corrupt Password Hash Hardening

Problem: `verify_password()` could raise on malformed stored hash strings or
invalid hex, turning corrupted credential state into a 500 instead of a clean
authentication failure.

Fix:
- `verify_password()` now returns `False` for malformed hash shape or invalid
  hex material.
- Added regression coverage for corrupt hashes and valid hashes.

### 7. Local CSP Compatibility

Problem: the web CSP always emitted `upgrade-insecure-requests`, even when the
configured app/API origins were localhost HTTP. That can break local browser API
calls by upgrading `http://localhost:8000` to HTTPS.

Fix:
- `upgrade-insecure-requests` is emitted only when both the app and API base URL
  are HTTPS.

### 8. Generated Test/Cache Noise

Problem: locked pytest/cache temp directories were not ignored broadly enough,
causing `git status` and `rg --files` warnings during audits.

Fix:
- Extended `.gitignore` for `.tmp-pytest*`, `.tmp-review*`,
  `pytest-basetemp*`, and `pytest-cache-files*` roots.
- Confirmed `rg --files` and `git status --short --branch` are warning-free.

## Verification

Passing checks run during this pass:

- `uv run ruff check src tests`
- `uv run pytest -q tests/test_file_security.py tests/test_document_storage.py tests/test_ocr.py tests/test_password_policy.py`
- `uv run pytest -q tests/test_virus_scan.py tests/test_portal_outside_counsel.py tests/test_document_worker.py tests/test_contracts.py`
- `uv run pytest -q tests/test_auth_cookies.py tests/test_session_revocation.py tests/test_security_settings.py tests/test_rate_limiting.py tests/test_tenant_isolation.py tests/test_webhook_security.py tests/test_sendgrid_webhook_security.py`
- `npm run typecheck:web`
- `npm run test:web`
- `npm run build:web`
- `npm audit --omit=dev`
- `npm audit`
- `pip-audit --path apps\api\.venv\Lib\site-packages`
- `uv pip check`

Notes:
- The full backend `uv run pytest -q` exceeded local timeouts twice (first at
  5 minutes, then at 15 minutes). Targeted high-risk backend suites covering the
  changed upload/storage/OCR/auth/security surfaces were run and passed.
- `gitleaks` is not installed locally; secret scanning was approximated with
  targeted regex searches and dependency audits.
