# Production checkpoint - `bc171a43` - 2026-08-23

## Exact release

- PR: `#307`
- PR head: `b17e9b512cc0c71997a091db673cb54796d304a2`
- Merge/deployed revision: `bc171a43f9f67917fef3eb1afcfad5ff765721ec`
- Exact-main CI: run `32594696280`, passed.
- Exact-main Security: run `32594696297`, passed.
- Exact-main CodeQL: run `32594696338`, passed.
- API revision: `caseops-api-00323-mnf`, 100% traffic.
- Web revision: `caseops-web-00301-mfd`, 100% traffic.
- Migration execution: `caseops-migrate-job-9rgjk`, passed.
- API digest: `sha256:362c2f38ce51e71c8cb3d1ec220805b2ec35948758922538fa53e4e7f1f838e1`.
- Web digest: `sha256:48817981c0d921811636369a3a7f94363759100a0ee635c5fa34b3b0c60d41ba`.
- API and web both reported the full exact release identity.
- Production health returned `{"status":"ok"}`.
- IP rule governance remained disabled.

## Exact-release production run

Workflow run `32596300438` checked out and verified the exact serving revision.

- Broad RAM batch: 77 passed, 1 failed, 4 skipped.
- Failing broad path: IPLF-026B at 360px; the access workspace did not render
  the `Preview grant` action expected by the production journey.
- IPLF-027B A0 quiescence acceptance: passed.
- Notice module: passed.
- IPLF-037B renewal acceptance: failed before fixture creation because all four
  governed calendar/rule version variables were absent. No replacement IDs
  were manufactured and rule governance was not enabled.

## Remaining proof

- Repair and rerun the IPLF-026B mobile access journey on an exact release.
- Supply only approved existing renewal calendar/rule version IDs before
  rerunning IPLF-037B production acceptance.
- Add an exact-release authenticated IPLF-038 reporting contract/browser check;
  deployment identity and health alone do not prove that contract.

This is a checkpoint, not a green production-acceptance claim.
