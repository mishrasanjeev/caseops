# Release Sign-Off Evidence

- Generated at: `YYYY-MM-DD HH:MM TZ`
- Reviewer: `name / agent`
- Environment: `prod / staging / preview`
- Target commit: `abcdef1`
- Deployed build fingerprint URL: `https://...` or `not available`
- Verdict: `GO` | `GO with caveat` | `NO-GO`

## Scope

- Release or change set under review:
- Bug sheet or ticket scope:
- Declared exclusions:

## Build Identity

- Expected commit:
- Observed commit or build id:
- Proof:
- If exact commit identity cannot be proven, state that explicitly here.

## Checks

| Check | Command / URL | Result | Notes |
| --- | --- | --- | --- |
| Backend verification | `scripts/verify-backend.ps1 ...` | pass/fail/skipped | |
| Web verification | `scripts/verify-web.ps1 ...` | pass/fail/skipped | |
| API health | `https://...` | pass/fail | |
| Web root | `https://...` | pass/fail | |
| Auth-gated endpoint | `https://...` | pass/fail | |
| Billing or provider-dependent proof | `manual / automated path` | pass/fail/skipped | |
| Public claim classification | landing / pricing / guide / README / llms | pass/fail | Every claim is live, review-first, provider-gated, founder-only, disabled until UAT, or planned |
| Production readiness gate | `/api/platform-admin/production-readiness` | pass/fail/skipped | Founder-only; list not-ready reasons |
| Secret rotation proof | `/api/platform-admin/secret-rotation-readiness` | pass/fail/skipped | No secret values stored or displayed |
| Provider/UAT blockers | Pine Labs / connectors / notifications | pass/fail/skipped | Explicitly blocked, provider-gated, or disabled until UAT |

## Caveats

- List every skipped check and why it still provides enough confidence, or say `None`.

## Commands Run

```text
scripts/verify-release.ps1 -ExpectedCommit abcdef1 ...
scripts/verify-backend.ps1 ...
scripts/verify-web.ps1 ...
```

## Reviewer Notes

- Record any manual observations, screenshots, deployment console metadata, or links to CI runs here.

## Fail-Closed Reminder

- Do not issue a clean `GO` if the deployed commit is unproven without fallback evidence.
- Do not issue a clean `GO` if a required smoke test was skipped without equivalent proof.
- If the verification environment was too broken to run the strongest practical checks, downgrade the verdict.
