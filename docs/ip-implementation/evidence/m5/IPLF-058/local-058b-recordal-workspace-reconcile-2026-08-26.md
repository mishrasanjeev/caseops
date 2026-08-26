# IPLF-058B recordal workspace reconciliation

**Date:** 2026-08-26

**State:** local correction and exact-production verification passed. Release
evidence is recorded in
`release-058b-recordal-workspace-reconcile-2026-08-26.md`.

## Trigger

Exact-production run `32940844298` passed 86 RAM tests and failed only the
IPLF-058B responsive recordal check. The page heading rendered, but the four
recordal tabs did not appear inside the 10-second visibility budget. Production
logs showed the selected recordal workspace request completing successfully
after 47.9 seconds during API scale-out. The UI hid its complete detail surface
behind that request and independently fanned out selected-docket, document,
Registry, and deadline requests.

## Correction

The selected-recordal workspace contract now returns the accessible docket,
at most the existing bounded docket-document set, Registry workspaces, and the
deadline workspace with the recordal, title, and transaction history. The page
therefore issues one aggregate detail request instead of separate supporting
requests. Its responsive tab shell is mounted from the selected list record
while the aggregate is pending, and each tab owns its loading or retry state.

The corpus-wide docket and document catalogues remain lazy. Create opens both
catalogues, while title-family review opens only the docket catalogue. The
aggregate does not activate a provider, filing, payment, Registry mutation, or
deadline automation.

## Local evidence

- Ruff passed for the changed API schema, service, and regression.
- API recordal foundation and journey suites: 6 passed.
- Recordal component suite: 5 passed, including an unresolved aggregate test
  that keeps all four tabs visible and proves no catalogue request starts.
- Web typecheck and production build passed.
- The dated IPLF-058B Playwright journey passed in 5.5 seconds. It asserts that
  all four tabs fit at 360 pixels before awaiting the aggregate, exactly one
  aggregate request occurs, and no selected-docket, document, Registry, or
  deadline supporting request occurs.
- OpenAPI client types were regenerated from the application schema.

PR #356 merged the correction to canonical main at
`3ce3e93e7ee07161c396344e0fe24d7a162216c2`. The exact release passed
migration-first deployment, identity verification, exact-main CI, and the
complete production verifier. Independent provider, legal-SME, and law-firm
UAT remain external acceptance and are not represented as repository work.
