# Native App Integration: 25 October 2026

J20/M22, US-MOB-01..08; J01/J03/J04/J08/J14 remain the server owners.
Status: **Partially implemented; native release NO-GO**. This checkpoint freezes
the integrated source before the real Android run, not an app-completion claim.

## Implemented Components

- Validated, isolated native identity/refresh/session revocation and real browser
  PKCE/MFA handoff. Malformed identity never reopens private screens.
- Today, identifier search, Matter detail/reload, notes, Calendar and draft/work
  reads; Compose Material 3 date picker and native iPhone date control preserve
  the recorded legal date using UTC conversion, not timezone arithmetic.
- Current-device/session controls, bounded trademark source reads with actual
  readiness/entitlement checks, and explicit unsupported contract-module states.
- Matter Files list and explicit system-picker upload. Only opaque parent,
  account, membership, login generation and original lifecycle version survive
  the picker; the root still discards private screens on background.
- Native uploads must send the original lifecycle version. The existing server
  lock checks it before and after scan/storage; legacy web forms remain compatible.
- Private PDF/image/TXT reader with pinned public PDF.js assets, no external
  file handoff, bounded streaming, hash verification, no-store and 15-second
  access leases. DOCX preview is intentionally unwired until its separate bounded
  transport/response policy is proven. Native memory/cache/renderer proof is open.
- Explicit local-only web API marker build. The browser itself sends the no-paid
  marker; the gateway never manufactures it. Production defaults do not change.
- Separate non-debug bundled Android acceptance profile with HTTPS-only public-CA
  trust scoped to the dedicated local binary. It needs no Metro development server.
  macOS gets a separate unsigned simulator profile, not weakened ATS.

## Component Evidence Before Native Execution

- Standard mobile inventory: **295 passed**, 20 intended/observed files, no
  failure/error/skip; strict full-app TypeScript passed. Report:
  `$HOME/.cache/caseops-mobile/mobile-integrated-20261025-freeze01.xml`.
- Build/harness/helper self-tests at that checkpoint: **88 passed**, three
  observed files, no failures/skips. Helpers under active fixture extension must
  be replayed after they close; this is not a native receipt.
- Web native-handoff/transport: **38 passed**, four intended/observed files.
- Upload owner: **60 PostgreSQL**, **41 mobile component**, **31 scanner/security/
  OpenAPI** checks passed. Raw failures and complete replacements are retained in
  `outputs/upload-fence-9e42`, with diagnoses in `apps/mobile/src/files/INTEGRATION.md`.
- Local Docker seed has real PostgreSQL, API/web, ClamAV, TLS, synthetic records,
  MFA and PKCE HTTP proof. Its initial API is d5a6641 and web identity unavailable
  because the marker source was dirty. **That old receipt does not certify the
  integrated candidate.** Rebuild both exact candidate images before acceptance.
- Initial viewer failures, corrected complete runs and public synthetic renderer
  pixels are retained outside Git in
  `$HOME/.cache/caseops-mobile/viewer-initial-20261025`.

## Native Acceptance And Explicit Gaps

The independent dated core inventory is **22 Android and 22 iOS cases**, not the
historical six. At this checkpoint none has run. See
`docs/mobile/ANDROID_CORE_INVENTORY_2026-10-25.md`; do not turn missing fixture,
source, browser consent or device access into a skip/pass. Follow exact source,
APK, Docker image, API/web revision, full collection and request-ledger evidence.

Metro launch was rejected before execution again. No alternate launcher, policy
change or proxy starts it. A finite Gradle release-style bundle is a normal
standalone build, not proof that the workstation's Metro restriction was fixed.
Owner authorized Firefox's free Terms of Use only for the dedicated emulator;
normal CA trust is configured through device/browser settings, never TLS-ignore.

Full MOB-01..40 closure still needs complete native source/GC/IP/files journeys,
inbox/push, accessibility/physical-device/privacy/session/capture/cache tests,
full shared Docker regression, registered production links, signing/distribution
and release review. Four existing high node-forge/Expo CLI findings are not waived;
Material 3 beta internals remain a separate review. No production deployment,
store availability or complete legal record verification follows from this work.

iOS remains ready for the owner's MacBook workflow, **not tested on Windows**.
Use `scripts/mobile/MACBOOK_RUNBOOK.md` and its actual simulator build/test script.
Latest native outcomes belong in a fresh dated sidecar; never rewrite a failed
run or mutate the build's source while acceptance is in progress.

## Retained Android Build Failures

The first local profile failed in Gradle configuration: the legacy `react`
property shadowed the typed ReactExtension. Its explicit typed extension lookup
now passes a retained red-to-green profile test. The replacement reached native
compilation, then Windows Ninja rejected a prefab path longer than 260 characters.
Object-name hashing does not shorten prefab configuration paths. The build wrapper
now uses AGP's supported `buildStagingDirectory` in a bounded, per-project/module
user cache through a Windows-only init script. No source alias, worktree, machine
long-path setting or security policy is changed. The complete build-tool input
closure is now included in the fingerprint. Component checks pass; the next
actual build is still required. Original build logs remain under the two unique
`$HOME/.cache/caseops-mobile/builds/android-*` directories.
