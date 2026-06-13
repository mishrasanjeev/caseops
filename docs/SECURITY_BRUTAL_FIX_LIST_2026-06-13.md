# Security Brutal Fix List - 2026-06-13

Scope: dependency advisories, secret exposure, auth/CSRF/route guards,
frontend XSS sinks, CI security gates, upload/provider hardening, and
high-risk code patterns.

## P0 - Historical Connector Secret

Status: blocked on external rotation.

Gitleaks found a historical `.codex/config.toml` `X-Client-Secret`
literal at commit `24c6ebf73f57605c964a908f78dfce686c68be1f`. The file is
not tracked now, but the exposed credential must be treated as burned.

Fix:
- Rotate the affected connector/client secret wherever it was issued.
- Keep the gitleaks finding unsuppressed until rotation is confirmed.
- Done in this pass: `.codex/` is now ignored to prevent recurrence.

2026-06-13 implementation update:
- Founder-only evidence fields now exist in
  `connector_secret_rotation_evidence` and are exposed through
  `GET /api/platform-admin/secret-rotation-readiness` and
  `POST /api/platform-admin/secret-rotation-readiness/evidence`.
- The paid-production console shows provider/app, credential label, rotation
  status, old-credential revocation proof, validation proof, last evidence
  timestamp, and residual risk.
- The evidence API rejects obvious credential values and has no field for a
  secret value. Store only external ticket/artifact references.
- Status remains provider/UAT blocked until the external issuer confirms
  rotation and old credential revocation.

## P1 - Secret Scanner Noise Masking Real Findings

Status: fixed, except for the intentionally unsuppressed rotated-secret
gate in P0.

The history scan also reported seven false positives:
- Cloud Build IDs / Artifact Registry image tags in release signoff docs.
- Matter-file-QA test scenario labels.

Fix done:
- Added exact `.gitleaksignore` fingerprints for only those seven
  false positives.
- Added directory-mode fingerprints for the same current release build
  IDs so local `gitleaks dir` scans do not fail on non-secret image tags.
- Added gitleaks path allowlists for generated dependency/cache/build
  directories that were making directory scans noisy and slow.
- Left the historical `.codex/config.toml` secret unsuppressed.

## P1 - Local Trace Artifacts Carry Session Material

Status: fixed locally and recurrence guard fixed.

A full working-tree gitleaks scan walked `.ci-artifact-debug/` and found
many JWT/session-looking values in extracted Playwright trace network
files. These are local ignored artifacts, but they are sensitive on disk.

Fix done:
- `.ci-artifact-debug/` is now ignored.
- Deleted the existing local `.ci-artifact-debug/` directory.

## P1 - Ignored Local Auth/Agent Files Carried Credentials

Status: fixed locally.

The broad working-tree scan found credential/session material in ignored
local files, including Playwright storage state and agent settings. These
were not source-controlled, but they were still sensitive on disk.

Fix done:
- Deleted ignored local Playwright auth state under `tests/e2e/.auth/`.
- Deleted ignored local `.claude/settings.local.json` files in the repo
  and local Claude worktrees.
- Deleted temporary gitleaks JSON reports generated during this audit.
- Added `.claude/worktrees/` and `apps/api/.uv-cache/` to `.gitignore`.

## P1 - Frontend XSS Sink In MFA QR Rendering

Status: fixed.

`apps/web/app/account/security/page.tsx` rendered MFA `qr_svg` using
`dangerouslySetInnerHTML`. The current API-generated SVG is escaped, but
inline SVG injection is an unnecessary browser execution surface.

Fix done:
- Render the SVG as a `data:image/svg+xml` image instead of inline markup.
- Added a Vitest assertion for the image data URI.

## P1 - CSP Allowed Inline Scripts

Status: fixed.

`apps/web/next.config.ts` used `script-src 'unsafe-inline'` for JSON-LD
and GA initialization. That weakened XSS containment.

Fix done:
- Moved CSP generation to nonce-aware Next proxy.
- Passed the nonce to JSON-LD and `next/script` call sites.
- Removed script `'unsafe-inline'`; retained style `'unsafe-inline'`
  separately until Tailwind/Radix/sonner style injection can be handled
  safely.

## P1 - Security Scanner Depth

Status: fixed.

CodeQL was running the default query set only.

Fix done:
- Enabled `security-extended,security-and-quality` in
  `.github/workflows/codeql.yml`.

## Current Automated Results

- `npm audit --audit-level=low`: 0 vulnerabilities.
- `uv --directory apps/api pip check`: compatible dependency graph.
- `uv --directory apps/api tool run pip-audit --strict --vulnerability-service osv`: no known Python vulnerabilities.
- `gitleaks dir .`: no leaks found after exact false-positive ignores and
  generated-directory allowlists; emitted permission-denied warnings for
  ignored pytest temp directories.
- `gitleaks git .`: one remaining finding for the historical
  `.codex/config.toml` connector secret until rotation is confirmed.
- Manual checks found no interpolated SQL `SELECT/UPDATE/DELETE/INSERT`
  f-strings; the one `text(f"""...`) SQL template uses constants.
- Route-guard and AI-rate-limit sweeps already exist in tests.
- Upload virus scanning fails closed in non-local environments when ClamAV
  is required.
