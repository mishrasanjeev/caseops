# BUG001 Scoped Rendering Handoff

Baseline: `2816c29c30d8f13147f67a396f47321871096f0d`.
Workbook: CaseOps_Bugs (5), BUG-001. The tester reported generic draft text;
PDF parity was explicitly unverified, not a reproduced PDF mismatch.

PRD ownership: J07 / M06, MOD-TS-012, US-018 / US-021, FT-027 / FT-029 /
FT-030, NFT-013 / NFT-014, SEC-003 / SEC-004. No global ledger changes.

## Route And Profile Audit

- `/api/drafting/preview` generates partial AI text. It is not a PDF preview
  and is unchanged. Neither acceptance fixture calls it or generation routes.
- The saved draft formerly used a sans-serif `pre`; selecting a court profile
  changed only `/api/matters/{matter}/drafts/{draft}/export.pdf`.
- The existing export route already supports `version_id` and `court_profile`.
  The new viewer pins both, renders its authenticated PDF bytes with the local
  PDF.js worker, and downloads that same blob after a fresh export authorization
  and SHA-256 comparison. Denial or changed bytes discards the artifact.
- PDF creation metadata now uses the persisted version timestamp, so an
  unchanged export is byte-stable across later authorization reads. A changed
  title, review state, body, citation list or preset cannot silently replace
  what the reviewer saw. Profile/version changes and unmount abort ownership.
- Existing access, citation and lawyer-review checks remain authoritative.
  No new filing approval, model call or legal-profile approval is introduced.
- The legacy court presets have no pinned official rule bytes, editions,
  effective dates or legal-review records. Their old documentation incorrectly
  described sources as pinned. Numeric settings and resolver policy are unchanged.
  The new layout digest identifies settings, not legal verification.
- The existing shared Matter export route's historical filing-grade description
  was not edited. A PDF and preview now explicitly warn that court rules are
  unverified and lawyer review remains necessary.
- A separate reproducible renderer defect used a non-wrapping court-header
  cell. Baseline synthetic long-header glyph bounds were -501.52..1093.07pt
  against printable 72..523.28pt. Wrapped headers pass the geometry regression.

## Browser Inventory And Fixture Environment

`ram-2026-11-11-drafting.spec.ts`: exactly **2 intended cases**, desktop and
`[mobile]` phone. The phone case creates a Pixel 5 touch context. There are no
explicit screenshot/video/trace commands; the parent configuration owns media.

Required runtime settings (all paths must refer to the checkout being tested):

```text
CASEOPS_E2E_PYTHON=<existing interpreter; no dependency synchronization>
PYTHONPATH=<checkout>/apps/api/src
CASEOPS_E2E_API_PORT=<isolated loopback API port>
CASEOPS_E2E_WEB_PORT=<isolated loopback web port>
CASEOPS_WEB_BASE_URL=http://127.0.0.1:<web port>
CASEOPS_ENV=e2e
CASEOPS_LLM_PROVIDER=mock
CASEOPS_EMBEDDING_PROVIDER=mock
CASEOPS_E2E_DATABASE_URL=sqlite+pysqlite:///<checkout>/caseops-e2e.db
CASEOPS_DATABASE_URL=<same database URL on the API process>
```

The imported `e2eEnv` supplies the normal local auth/CORS/storage settings.
`CASEOPS_E2E_DATABASE_URL` may be omitted for the exact checkout-local SQLite
default. The existing shared fixture guard also permits only the dedicated
loopback PostgreSQL acceptance connection (`caseops` database/user/password,
explicit port 20000..49999, no URL query overrides). No shared application DB.

The spec bootstraps unique synthetic local tenants and blank drafts, persists a
layout-only version, then uses real submit/approve routes. Its synthetic citation
count is a fixture, not verified legal authority or evidence of content quality.
It compares every rendered page's nonblank canvas and the downloaded artifact
hash, changes profile, reloads, and checks persisted content/reviews are unchanged.
Every browser API request must retain the no-paid-providers marker. Non-loopback
targets and generation requests fail before acceptance. This is not a production
mutation or production acceptance spec.

## Evidence Limits

Focused unit/API journals, JSON/XML reports and synthetic PDF renders are in the
owning worktree's `.tmp` and `apps/web/.tmp`, not committed release evidence.
Final focused results: `bug001-api-04.jsonl` / XML contain all 37 intended unique
cases (4 new, 25 profile, 8 existing PDF/profile-route cases), with 111 passed
setup/call/teardown records and completion exit 0. `bug001-web-06.json` contains
33 passes across both intended modules (21 artifact, 12 page). Scoped frontend
and E2E TypeScript checks and the owned Python Ruff check pass.
Checks used the existing `ai1107` Python environment with this checkout's
`PYTHONPATH`, and Node 24.15.0 with read-only existing npm dependencies and a
Vite root pinned to this checkout. They are not pinned release-runtime gates.

The default Playwright config discovers both dated cases. On this branch's
unchanged app config, only desktop is discovered after the required `[mobile]`
tag: the parent configuration agent must add this spec to the mobile allowlist
and reconcile the final inventory to exactly 2. Discovery is not execution.

The initial browser attempts failed fixture setup because the server normalizes
Matter codes to uppercase; the exact guard is corrected and directly exercised.
Those attempts did not reach the UI and must not be called parity passes.

Parent owns built-app desktop/mobile replay, canonical configuration, exact
release verification, production-safe media policy and workbook adjudication.
Production acceptance remains **Inconclusive**. Placeholder court/party text,
irrelevant authorities, drafting quality and jurisdiction/document-specific
reviewed legal-profile data remain separate unresolved dependencies. This patch
does not certify legal suitability or close the whole BUG001 report.
