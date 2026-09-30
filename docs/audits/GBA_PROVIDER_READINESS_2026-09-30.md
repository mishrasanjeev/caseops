# GBA provider readiness: 2026-09-30

Verdict: **NO-GO** for the claim that every provider works end to end for GBA.
This is a read-only production audit of `gba-law` on the API/web tree
`37d54ec9cffd52100425452f4a4c8235f1674c53`, plus source and local test
inspection. The subsequent code patch is not production evidence until merged,
deployed and tested on the exact serving revision. No paid provider call or GBA
write was made during this audit.

| Capability | Status | Production evidence and remaining gate |
| --- | --- | --- |
| eCourts tracking | Partially implemented | Token and schedule are configured, but connector health is degraded/failed. GBA has 586 tracked cases; only 46 have ever succeeded. Of 583 eligible, 538 were due; 534 lacked CNR and 535 lacked a court code. The last five scheduled runs were partial. The latest checked 0, blocked 44, made 6 provider calls and left 538 backlogged. The Cloud Run job's exit 0 is not a tenant-success signal. Exact case-number search with no code is now blocked locally before transport/spend, and skipped rows remain counted. A reviewed CNR or provider-published court code is still needed for the affected records; no code may be guessed from court name. Require a meaningful returned case, linked hearing date after reload and two clean 18:00-20:00 IST cadences before closure. |
| Indian Kanoon | Partially implemented | Tenant has an active provider-spend exception and production binds a token, terms and positive budgets. Five recent searches do not prove a meaningful legal result, current provider balance or exact-source acceptance. Keep no-paid automated tests and obtain a funded human-owned canary with reviewed attribution and current terms. |
| OpenAI and Voyage | Partially implemented | API key bindings and selected models exist; GBA's assistant policy is enabled. This does not prove quota, grounded output, embedding quality or a complete GBA matter journey. Verify funded account state and exact-source output under the existing review controls. |
| SendGrid email | Partially implemented | Key, sender and webhook public-key bindings exist, but external delivery is disabled at runtime. Four recent GBA email intents were blocked; none was delivered. Verify authenticated sender, consent, callback and delivery before enabling. In-app notifications remain usable. |
| Google Workspace Gmail, Calendar and Drive | Missing | APIs may be enabled in GCP, but production OAuth bindings and GBA user connections are absent; connector health says `missing_config`. Google Cloud ownership cannot grant GBA mailbox/calendar/Drive consent. Complete OAuth and tenant-authorized connections. |
| Microsoft 365, Outlook and OneDrive | Missing | No production Entra OAuth configuration or GBA connection. Requires Microsoft app/tenant consent. |
| SMS and WhatsApp | Missing | Disabled, no approved sender/template or callback credentials. Do not present a user preference toggle as working delivery. |
| Pine Labs Plural | Missing | Payment links and subscriptions are off. Merchant credentials, signed webhook, UAT reconciliation and reviewed activation are absent. |
| IP India / WIPO registry | Missing | Live lawful-access/provider contract and production adapter remain absent. No scraping workaround. |

## Root cause and recurrence

The scheduler admitted legacy Matter-linked bookmarks identified only by a case
number and human court name. The eCourts exact-search API uses a public
registration/filing number plus provider court code; its `courtName` field is
not a safe substitute for the indexed `courtCodes` filter. The search could
therefore consume credit yet return incomplete candidates. Failing closed after
the response prevented a wrong match but did not prevent repeat paid attempts.
The adapter now rejects that query before transport; the service additionally
checks before spend reservation and excludes unsearchable rows from its bounded
scheduled batch without hiding them from blocked/backlog metrics. This is a
prevention fix, not a backfill of verified identities or a claim that GBA is
green. Local regressions cover no transport/spend, short valid codes, CNR,
legacy hearing sync and the GBA PRD.

The human-approved window is **18:00-20:00 Asia/Kolkata for every tenant**.
This supersedes the source GBA document's 16:00-18:00 request. Scheduled
provider eligibility is separate from configured credentials, completed job
exit code, and current browser policy. No paid automated acceptance is allowed.

## Retained release-gate failure

The committed first candidate `92eb79bf9aea1adbe4ae59257836d3d41d5a88ba`
passed all **461/461** PostgreSQL/pgvector tests and index-health checks in
fresh Docker on 2026-09-30. Its selected Playwright inventory was six tests in
the two requested dated hearing files. The CNR journey passed; the older
case-number and combined registration/filing journeys failed because their
no-code Matters did not gain the expected hearing date. Three local-inapplicable
tests were skipped. This is a **failed** acceptance, not a release certificate.
Retained files: `.tmp/docker-acceptance/b50b6f3fe8344d9393b8456061d079cb/`
and the two dated `test-results/` error contexts. The subsequent browser
correction must prove both visible no-code blocking and a successful
provider-code-backed Matter link on a new committed image; it has not yet
replaced that failure.

The second committed candidate `9369d6ae449adf3a6ce602d2cab485999447aeea`
completed the same 461-identity PostgreSQL collection with 458 call passes,
three call failures, and 461 passing setups/teardowns. Its Playwright phase
was correctly withheld. The three failures independently showed that the new
court-code hint masked the pre-existing missing-court and missing-case-type
messages. The corrected priority and current-Matter-CNR read check passed
all five exact PostgreSQL repros and a 136-test local hearing/provider matrix;
the latter is not a replacement Docker release verdict. The second run is
retained at `.tmp/docker-acceptance/58e620899c764440a37ab558846b8f00/`.

The third committed candidate `403dbaa237e66bda1c8ad736be086be65d1e61e9`
completed the same 461-identity PostgreSQL collection with 460 call passes,
one call failure, and all 461 setups/teardowns passing. The provider-wait
concurrency test did not enter its mocked transport within five seconds during
the full run. It passed alone against fresh PostgreSQL, which does not erase
the full-suite failure or establish its cause. Playwright was withheld.
Retained report: `.tmp/docker-acceptance/00f33705bf084b1e8eb003e736177776/`.

The fourth committed candidate `2783c4130fa74eddd3be4118048987669907b3d7`
passed all **461/461** PostgreSQL tests and the complete post-rehearsal index
health check. Its six-test dated Playwright inventory had one pass, two
failures and three expected local-inapplicable skips. Both failures showed
that a reviewed provider link left a legacy code-less auto-link active beside
the verified bookmark on the same Matter. The two failures have separate
retained `test-results/` contexts; the full gate is retained at
`.tmp/docker-acceptance/9eabd7dd79b843999471ddc2e759f3df/`. The
reconciliation fix and its SQLite/PostgreSQL regressions were local changes,
not an accepted or deployed release.

The fifth committed candidate `798d0fe20984f591c7b55da2718c5942c24d7274`
passed all **462/462** selected PostgreSQL tests, post-rehearsal index health,
and all four locally applicable dated Playwright journeys. The two
production-only journeys were explicitly skipped locally; neither is a
production acceptance claim. Retained gate:
`.tmp/docker-acceptance/ae57dc9dab754cddb6917777831feed9/`.
PR #506 still has security/dependency and data-governance CI failures, so
this candidate is not releasable or deployed.

The sixth candidate `2305ff6d521f277f4b8a409833ffc7c642accba3`
cleared the local dependency audit, 1,108 web tests, web build/typecheck,
53 focused authentication tests and both governance-map checks. Its Docker
run was deliberately interrupted after image/index checks because CI found
the generated data-class projection stale; no completed PostgreSQL or browser
result is claimed for that run. Its partial journal remains at
`.tmp/docker-acceptance/5bcc2b7f2fb4417993a179cf8fe2ef1a/`.

The seventh candidate `1e9b3bd36c9a90ac0309e6bbe8c43af9ff50d2c1`
cleared security/governance checks but failed CI API coverage shard 5: four
dated combined-hearing emulator cases still searched by case number without
a provider court code. Its Docker run was interrupted after the first part of
the PostgreSQL matrix because this CI failure made the candidate
non-releasable; the partial journal is retained at
`.tmp/docker-acceptance/ab92d580504946cea89af26401e0bdc6/`.
The revised dated fixtures now use their own published codes (`DLHC01` for
the September 10 hearing fixture, `DLHC` for the older base fixture). The
54-test local emulator/matching matrix passes, including the no-code
pre-transport rejection. This does not replace full CI or Docker acceptance.

PRD scope: journeys J03/J05/J08, modules M02/M04/M08, US-057..059 and
FT-078..088. BUG-012 and BUG-014 remain open until the full browser journeys
and exact-production release proof pass. A no-charge rejection alone does not
meet the next-hearing requirement.

## Release and production verification update (2026-09-30)

PR #506 was accepted on Docker at `bec958ba` (462/462 PostgreSQL tests,
four locally applicable dated Playwright journeys passing, two production-only
skips), merged to main at `ba6468f1`, and deployed. The accepted and merged
trees were identical. Production API revision `caseops-api-00477-pwk` and web
revision `caseops-web-00454-w62` both serve that release with 100% traffic.
Migration, statute seed, hearing backfill, index health, QA bootstrap and
health/ClamAV gates passed. The 18:00-20:00 IST case-tracking scheduler resumed.

Exact-release production verification [run 36683747177](https://github.com/mishrasanjeev/caseops/actions/runs/36683747177)
found two tester-journey failures: the new pre-spend court-code rejection was
safe but omitted the established `No external request was made.` user-visible
assurance. These failures are not waived. A follow-up regression now checks
that exact response, zero provider transport and zero spend reservation, as
well as the tracked-case refresh path. The replacement release is pending full
Docker and CI acceptance, merge, deploy and production replay. The
private-projection maintenance scheduler remains intentionally paused until
successful exact-release verification and two clean serial maintenance runs.

GBA was audited with a read-only Cloud SQL transaction after deployment: 586
tracked eCourts cases, 583 eligible, 538 due, 534 without CNR and 535 without
court code; only 46 have ever succeeded or have a hearing. Missing official
identities and vendor authorization remain external blockers. This release
does not make GBA all-provider-ready.

PR #507's first CI run failed one workflow inventory assertion because the
new read-only shard was not added to that test's expected matrix. The next
candidate `33b76f8b` corrected the inventory and passed focused API tests,
but CI identified an unupdated data-governance map after comparison with
current `origin/main`. Its Docker gate was interrupted after build and index
health, before PostgreSQL and Playwright; the partial report is retained at
`.tmp/docker-acceptance/936f912bd2d24dcf8884c7f307014866/` and is not
acceptance evidence. The governance note and generated view are updated in
the next candidate. Full CI, Docker and production verification remain open.

## Closure gates

1. Obtain the GBA court/identifier inventory from an authorized owner. Review
   official provider codes or CNRs and correct records through audited product
   paths; 280 tracked rows have no court name or code at all. Do not infer a
   mapping from similarly named records or write directly to the tenant DB.
2. Run a funded, authorized **human** eCourts exact-case lookup and hearing
   reload for a specified GBA Matter. Automated verification remains no-paid.
3. Obtain vendor account, sender, OAuth consent and merchant/registry evidence
   for each desired external integration. The guide is
   `docs/runbooks/provider-setup-2026-09-24.md`.
4. Merge the prevention patch to main, run full Docker/PostgreSQL and Playwright
   acceptance, deploy exact main, and verify the actual serving API/web SHA.
   Recheck GBA read-only connector health and two clean scheduled cadences.
   Without these gates, do not mark this audit implemented or production green.
