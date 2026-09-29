# Saved Manifest Later Events: Deployed Sister Proof

Verdict: **Inconclusive** until the combined candidate completes Docker and
exact-release production Playwright. This patch adds acceptance, not a service
fix or a production-pass claim. Base: `8eff6eb4fedcded9254d9e58d1a8e783be225306`.
Parent owns integration with #500 and full release verification.

## Legitimate Boundary

The original Review producer remains unprobeable for this exact unchanged-source
failure shape: it captures Matter/docket targets, whose real access/lifecycle
events change their source versions. No Review, recommendation, authority,
approval, model run, or verified-citation count is fabricated by this fixture.

The sister surface is a synthetic, manually authored Draft backed by an indexed
Matter document. Its SHA-256 source version is unchanged by parent access and
lifecycle events. The release-owned fixture calls the real capture path, freezes
writer-shaped Draft versions, rebuilds without changing the captured sources,
and positively checks member reauthorization after retirement. Local browser
manual edits exercise the real writer and retain the exact capture contract.

Citation-free Draft exports legitimately return `422 verified_citations_required`
before revocation. After the later event, DOCX and PDF must instead return the
earlier `409` private-source refusal. **Successful export rendering is not
claimed**: it needs a legitimately citation-grounded producer. An invented
citation/approval would invalidate this proof.

## Journey And Reruns

Test ID: `IPLF-UJ-66C` in
`tests/e2e/iplf-066c-saved-manifest-later-events-2026-09-29.spec.ts`.

- Check API and web against the exact expected candidate SHA, including at exit.
- Discover release-owned fixture IDs through authenticated APIs, not browser DB
  writes. Use a dedicated non-owner QA member to prove an actual ethical wall.
- In Docker, positively read lists/details/body after benign retirement and reload.
- In Docker, add/remove a wall through the owner API; separately dispose/reopen the second
  document's Matter through the lifecycle API and concurrency token.
- In Docker, explicitly rebuild and require a genuinely new, settled generation.
  Source document hashes and current member access must be restored.
- After reload, stale Drafts disappear from lists, details show a load error,
  private body/download controls are absent, and detail/DOCX/PDF APIs refuse.
  An unrelated control remains visible/readable in that same generation.
- Production validates retained release-seed evidence instead of mutating sources
  or waiting on cadence. The seed calls the canonical wall/lifecycle API service
  producers, proves actual member exclusion/restoration, then rebuilds and asserts
  both old manifests remain locked while the unchanged control is current. It
  records the actual audit IDs and post-event generation/activation time in the
  control's QA context annotation; browser acceptance reconciles those audit IDs,
  actor, success result, and retirement -> events -> rebuild chronology.
- The final retained read loop reloads at 1280px and 360px, proves both control
  body and download action can enter the viewport, excludes stale list/detail
  controls, and checks document width, noncollapsed body and nonoverlapping
  body/download geometry. Mutation phases are not repeated for responsive reads.
- Reruns read retained revocation and successful later-than-retirement audit
  events; they never rewrite stale versions, recapture, or reopen terminal rows.
  Missing, partial, interrupted, or drifted evidence fails, never skips.

## Runtime Gates

Standard app/Docker discovery already matches the new dated `iplf-066c` filename.
Production config explicitly includes it in `tester-prod-chromium`, so the
existing canonical tester workflow executes it without a new workflow job.

Fresh Docker uses the project's candidate `baseURL`, canonical API port,
`CASEOPS_RELEASE_SHA`, `CASEOPS_E2E_DATABASE_URL`, `CASEOPS_E2E_PYTHON`, and `e2eEnv`.
The loopback-only helper calls the release fixture bootstrap and bounded rebuild
with `CASEOPS_LLM_PROVIDER=mock`; non-loopback browser/API/database targets are
rejected. It seeds no authority corpus. Local QA credentials have an offline
default; existing different credentials must be supplied, never overwritten.

Production never runs Python seeding or a cloud command from the browser.
The normal release bootstrap now includes this fixture after the existing IP
fixtures and reads the existing `CASEOPS_QA_RELEASE_SHA` / IP QA password secret.
It creates one server-owned QA member, never rotates that member's credential,
and never rewrites entitlements from the browser. All browser and API contexts
carry `X-CaseOps-Automated-Test: no-paid-providers`; no generation/provider route
is invoked. Rebuilds retain their default external-provider prohibition.

The release seed must run serially before browser QA. Cadence remains PAUSED
through normal production verification and the parent's two clean maintenance
runs afterward remain mandatory. Production performs no integrity polling;
earlier canary pending events cannot turn this into a wait on paused cadence.
The integrity helper rejects non-loopback targets and bounds only the explicitly
invoked local rebuild to 30 seconds. Disabled AI policy is never enabled by this
test. Serialize the release seed with other QA-tenant mutations.

## Narrow Evidence

- First fixture run: 8 passed, 2 failed at the legitimate citation export gate;
  preserved rather than weakened into a fake positive export.
- Replacement fixture run: 10 passed, 10 collected identities and 30 successful
  setup/call/teardown reports; both event cases demonstrate old-predicate revival.
- First serialized-seed run: 20 passed, 1 failed because the Matter default was
  Active rather than the fixture's required Intake. Preserved evidence; the
  synthetic fixture now explicitly starts in Intake before dispose/reopen.
- Final canonical fixture verification: **21 passed**, comprising 9 existing IP
  bootstrap cases and 12 narrow saved-manifest cases. Collection, JUnit and all
  63 successful setup/call/teardown reports agree; session completion exit was 0.
  This includes terminal-source preservation and serialized production seed/replay.
- `npm run typecheck:e2e` passed.
- Docker/app-chromium discovery: 1 journey in 1 file.
- Production/tester-prod-chromium discovery: the same 1 journey in 1 file.

Local retained evidence directory:
`C:\Users\mishr\.codex\release-evidence\saved-manifest-proof-20260929`.
No Docker browser run, deployed browser run, cloud write, merge, or push was
performed by this worker. Original Review and positive rendered-export proof
remain explicitly outside the verified claim.
