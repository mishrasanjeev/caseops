# November 17 production verification follow-up

Status: **Partially implemented / Inconclusive; NO-GO for complete release certification.**

## Exact deployed release and retained failure

PRs612,621 and623 have merged. The canonical retry deployed
`acff6c866bb7734e6ca3c3705b19b7f2392cb38f`; API revision
`caseops-api-00526-78v` and web revision `caseops-web-00501-576` serve100% latest
untagged traffic. Public release identity, health, scanner, edge, backup,
migration, worker activation and index checks passed. Document processing,
court sync and18:00 case tracking resumed through the canonical guards.
Private projection maintenance remains paused pending complete production QA
and the existing two-clean-execution recovery guard.

[Production dispatch44011493757](https://github.com/mishrasanjeev/caseops/actions/runs/44011493757)
failed its first tester partition:101 cases,84 passed,13 skipped and four
failed. These are separate outcomes; the partition and release are not green.
[Retained native artifact14297698983](https://github.com/mishrasanjeev/caseops/actions/runs/44011493757/artifacts/14297698983)
binds the exact source, configuration, zero retries and failure locations.
The other production partitions were still running when this note was added.

All four failures are the desktop/phone Registry and patent-family reference
checks in `tests/e2e/ram-2026-11-14-prod.spec.ts`. Their errors locate the
`prepareTester` production tenant refusal at the original
`tests/e2e/support/ram-bugs4.ts:231`. The job log records
`CASEOPS_RAM_PROD_SLUG=caseops-qa`; that helper permits only `test-legal`.
The tests failed before authenticating or opening the reference pages.
Their subsequent UI assertions remain unverified, not failed product behavior.

## Account binding repair

Existing J08/M08 owns these read-only reference journeys. Keep every test name,
UI assertion and deadline. Move the four reference cases from the QA-bot
project into the existing serialized reporting project and its second
invocation. Preserve the unchanged helper and existing workflow credentials.
The reviewed partitions become97/18/6/40/15; their complete176-case
semantic union and all original51 dated identities are unchanged. Independent
Python and frontend contracts must prove every literal identity and role,
with an actual zero-retry pass required for each reference. No account,
entitlement or production password is created, reset or broadened. Local
execution retains its fresh owned tenant and local-only setup.

An earlier explicit-purpose credential-binding alternative passed10 focused
VM controls after its negative baseline, but does not satisfy the current
release instruction to use the existing serialized role. Preserve that
alternative externally; its interrupted complete API attempt is incomplete,
and its new helper/test are not part of the final change.79 focused Python
identity, partition and positive-receipt controls pass after the role move.
The first frontend inventory replay timed out during native discovery;
34 cases passed and15 hook-dependent cases remain unverified. The initial
wrong-cwd invocation discovered no tests and is retained separately.
No collection or preparation deadline is widened. Complete source, frontend,
CI and exact-serving production replay remain required.

## Next.js dependency repair

The fresh root npm audit flags Next16.4.2 for
[GHSA-mfr8-8qww-v76h](https://github.com/vercel/next.js/security/advisories/GHSA-mfr8-8qww-v76h).
The maintainer describes root-parameter cache disclosure when application code
combines `use cache` with `unstable_cache()`, and identifies16.4.5 as patched.
No matching cache API usage was found in the first-party web source; that
observation does not waive the affected dependency or certify every possible
runtime path. Existing CI's high/critical threshold explains why a moderate
advisory can coexist with passing earlier source checks.

Pin current stable Next16.4.6, reconcile all locked and installed Next/compiler
identities, and retain the actual MIT package attribution shipped by the full
production `node_modules` copy. The version-specific native TLS worker fixture
must exercise the new installed runtime with its original verification and
deadlines. Keep existing license exceptions and TLS policy unchanged.
The targeted install reports zero vulnerabilities; fresh complete security,
platform-installed license, type/build/Docker and deployed workflow evidence
remain necessary. Registry provenance and the original failing audit are
retained separately in the operator's release evidence.

The exact1079-byte MIT license also ships as a public notice and a retained
source copy, independently pinned to upstream commit
`54b876b6b161b0ecda19562eb264bec637e60d6d` and SHA-256
`ee765244e2d59f5234d474f62e0766fa0c8b99af967fdd4c0cb8dcb0c76ea224`.
The public catalog now has12 components/15 notices; the native upload contract
requires74 exact material paths. Existing exception registries are unchanged.

The first native upload replay retained12 passes/one failure from a missed
operator-count consumer (`58 != 57`). After reconciling that separate count,
all13 native discovery, builder-input and exclusion controls pass in205.447s.
The image's independent hash-bound retained-source inventory must also include
the new base-policy MIT material:57 retained files/58 total operator records.
Its original19 reviewed exception entries remain unchanged.

The complete packaging contract also reproduced a pre-existing Windows JSON
decoding error: default cp1252 mangles the Node notice while both original and
current UTF-8 JSON match the unchanged pinned public/source bytes. Make every
text read in that contract explicitly UTF-8. A physical child regression owns
its non-UTF-8 locale, verifies its actual UTF-8 flag is off, and calls the real
Node notice guard; its original failing result retains those runtime facts.
No process-global locale patch, text normalization or fingerprint change is used.

The pinned npm11 producer regenerated the original382-entry lock in a fresh
owned stage. All10 Next/env/compiler identities retain the image's root
layout at16.4.6. The sole unrelated metadata difference removes `dev: true`
from optional Darwin-only `fsevents@2.3.2`; its version, integrity, MIT terms,
platform, engines and install-script flag are unchanged. This exact difference
is retained and reviewed separately from runtime identity changes.

Windows npm-tool preparation retained two incomplete attempts: an unsafe
inherited temporary-directory write scope was refused, and a later private
preparation exceeded its unchanged30-second budget. The fresh private lock
producer did complete under that budget. These are preparation outcomes,
not dependency-audit verdicts or proof of a repaired Windows timing issue.
The web dependency installation follows its canonical `npm ci` path;
the separately changed native TLS fixture still needs actual consumer proof.

## Other acceptance limits

The earlier complete Windows attempt retained803 passes/one failure among804
executed cases: an IP import resume exceeded the unchanged90-second limit.
The remaining3398 native cases and Windows browser inventory were not run.
A later276-case prefix passed, but did not establish the original cause or
complete that Windows gate. Preserve both scopes and the original failure.

The November15 format-generation desktop/phone journeys are deliberately
synthetic and loopback-only. Their source-CI passes do not establish production
model quality, legal accuracy or filing readiness. Do not put those fixtures
into the production inventory or count them as live production acceptance.

## Later production partition failure

The same dispatch's second reporting partition completed9 passes and
two failures, both IP18 saved-view POST assertions at line167 on desktop
and phone. Exact revision00526 request logs show409 for both requests.
The later Notes22 case itself passed; its whole-document guard rejected
the failed partition, which does not erase that row-specific pass.
Calendar readiness and the other completed sibling journeys retain their
own passing evidence. Saved-view quota/name-conflict diagnosis is pending;
do not delete retained data, raise the50-view limit or call later export
assertions verified. Artifact14302073924 retains the full native report.
A second private mobile dependency preparation also exceeded its original
30-second deadline; native TLS consumer proof remains incomplete.
