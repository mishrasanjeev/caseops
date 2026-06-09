# Bug Reopen Learnings - Hari 2026-06-09

Source: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari09Jun2026.xlsx`.

## Where I Went Wrong

1. I treated an admin POST route as a complete save workflow. The UI kept creating a default billing profile instead of updating the existing tenant default, so repeat saves could collide with tenant uniqueness and feel like the workspace API was broken.
2. I treated "PDF endpoint returns bytes" as enough. Browser downloads can still fail through cross-origin fetch behavior or object URL timing. File workflows need browser download proof, not only API response proof.
3. I treated backend PATCH support as product support. Matter status could be updated by API, but the matter portfolio gave users no visible status-change control.
4. I rendered provider source URLs directly in tenant UI. eCourts source documents require provider bearer auth, so a browser link to `webapi.ecourtsindia.com` is structurally wrong and leaks the provider boundary into the tenant experience.
5. I allowed raw provider metadata shapes to reach tenant responses. Even if the UI ignores a field today, tenant APIs must not expose raw provider URLs, tokens, signatures, raw payloads, or internal provider artifacts.

## Permanent Rules

- A "Save" button must be idempotent when the product object is a singleton/default. Use update/upsert behavior rather than repeated creates.
- Download bugs are fixed only after the browser path is tested: click, download event, filename, and API auth/CORS behavior.
- If a backend mutation exists, the relevant product page still needs a visible, permission-aligned control and regression coverage.
- Tenant UI must never link directly to authenticated provider documents. Source access goes through CaseOps routes that validate tenant ownership and apply provider credentials server-side.
- Tenant API serializers must scrub raw provider metadata, external source URLs, tokens, signatures, webhook secrets, raw payloads, and provider-only notes.
- Every reopened Hari/Ram bug batch must add a focused Playwright regression file and register it in the normal app Playwright config.

## Regression Anchors Added

- BUG-054: `/app/admin/matter-billing` saves the default billing profile; repeated saves update the existing default.
- BUG-055: matter invoice PDF downloads use a hardened browser download helper with direct-download fallback.
- BUG-056: `/app/matters` exposes a status selector for users with `matters:edit` and calls the tenant-scoped PATCH route.
- BUG-057: `/app/case-tracking` renders CaseOps source proxy URLs, while the backend hides raw provider URLs from tenant update responses and downloads source PDFs with server-side provider auth.
