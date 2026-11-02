# Native App Integration: 25 October 2026

## Later Runtime Findings And Replacement

The source80b full run reached all 23 setup/call/teardown identities and passed
postflight, but is **not acceptance**: 10 calls passed, three direct call failures
and subsequent modal-blocked setup left 10 calls unexecuted. Authentication,
tabs/Today, all five identifier/reload/restart journeys, invalid-date rejection
and saved draft/version reads passed. The note POST was acknowledged once;
manual same-actor read proved its exact saved body and ID remained present.
Android flattened its row identity marker away from the body in the accessibility
tree. Every body now has its own stable note-body ID. Mobile298 in all 21 intended
files and strict TypeScript pass; rebuilt device replay remains required.

Calendar reload succeeded through the actual enabled button ID. Android's native
unsaved-note dialog exposed STAY / LEAVE EDITOR with canonical button IDs, not the
source labels' title case. The harness now uses those observed controls, records
ID-only native steps, recovers failed local UI without a note replay and declares
real browser reauthentication before its second group. The 15-minute MFA policy,
existing note and untouched lifecycle/access negative targets remain unchanged.
Native127 tooling tests pass. The current-session revoke control also has a
server-current-flag-owned stable ID. Historical six-case receipts/mappings stay unchanged;
their positional latest-body selector does not certify the current dated core.

Source `60f1decc` produced an actual standalone non-debug Android APK and matching
Docker API/web images. Manual real-browser password/MFA, native Today/Account,
sign-out and signed-out Home/return were observed. None certified the full core.
The first 23-case attempt was interrupted after browser failure; two subsequent
completed reports each retain zero successful calls and 22 blocked downstream
cases. No note/lifecycle mutation occurred in those blocked attempts.

The test harness now explicitly configures/readbacks exact resource IDs, fills
MFA before locating its enabled submit, waits for request-backed states without
pull-to-refresh, records secret-free steps/session IDs and blocks downstream
setup after initial auth fails. Its dynamic current-session deletion proof is
hash-bound to real gateway source/status/isolation; the bounded 64-event history
retains all events and rejects overflow, without a route wildcard or fake ID.

Actual Firefox exploration additionally proved an unreliable asynchronous app
launch after authorization. The replacement requires an explicit Open CaseOps
gesture after one acknowledged grant. Server lifetime bounds the memory-only
callback; response latency, query changes, pagehide, hidden state, expiry and
double clicks cannot extend/replay it. Four intended web files pass **79 cases**
with zero failures/skips; strict web TypeScript passes. The earlier three-file
63-case filter and timer-fixture failure/interruption remain incomplete evidence,
not replacement passes. Fresh source-frozen API/web/APK and native replay follow.

Mac fixture helpers now select iOS loopback origins and observe the dedicated
simulator locale without Android tooling. **Actual Mac/Xcode remains NOT RUN**;
see `scripts/mobile/MACBOOK_RUNBOOK.md` and the dated iOS owner checklist.

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

## First Actual Device Findings

The 51036056 Android candidate compiled successfully: 655 Gradle tasks, 7m6s,
non-debug local acceptance APK. The first packaging verifier incorrectly assumed
an unoptimized resource ZIP path; aapt proves the actual manifest/network/CA
resource-ID chain and pinned bytes. The corrected verifier has a retained
reproduction and complete component replacement; a new wrapper run is required.

Actual native startup and system-browser navigation were exercised, not a core
acceptance pass. The emulator's default WebView Shell was replaced through normal
default-browser settings with the already verified Firefox; no production browser
or OS security policy changed. Raw public control observations stay outside Git.

Two real native-path defects were discovered before certification:

- Signed-out return from background could retain the privacy cover because only
  a ref changed. Foreground visibility now has React state. NATIVE-23 adds an
  actual Home/return/no-auth-request regression; its rebuilt execution is pending.
- An enrolled user under optional login-MFA policy could reach native consent
  without fresh same-browser MFA. The server correctly refused Connect, but the
  page lacked a verification form. The refusal now has type `native_mfa_required`;
  consent invokes the existing TOTP step-up, checks the same current principal
  afterward and requires another explicit Connect. There is no automatic grant or
  mutation replay. Ordinary forbidden responses never open that MFA recovery.

Replacement web inventory: **44 passed in four intended files**; full web/mobile
TypeScript and all **295 mobile component cases** pass. Backend native/MFA
inventory: **49 passed, including eight real PostgreSQL cases**, retaining the
pre-fix failure under `outputs/native-mfa-9mf7`. The native inventory now has
**23 cases per platform** and requires explicit login-versus-consent MFA staging.
These are component/discovery results, not completed native execution. The initial
438 API/web Docker receipts remain historical; rebuild after this batch freezes.
