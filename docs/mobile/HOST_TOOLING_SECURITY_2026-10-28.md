# Scoped host Node trust and native tooling (2026-10-28)

This is host preparation, not native application or store acceptance. The old
Appium 3.8.0 and driver homes remain retained failed dependency scopes. Earlier
package-advisory responses remain useful package evidence; they were fetched
before the host Node trust remediation and do not establish clean TLS defaults.

The current source pins Node 24.15.0/npm 11.12.1, Appium 3.9.0, WebdriverIO
10.1.0, XCUITest 12.22.2 and UiAutomator2 8.7.3. Use official releases, without
an override or modified package version. Old XCUITest 12.20.0 and UiAutomator2
8.7.0 bundle vulnerable exact dependencies; resolving the core alone cannot
certify those driver homes. Every actual nested installed identity and hidden
home-lock node must be inventoried. Absent optional packages are explicit
omissions, including platform-matching optional binaries, rather than silently
accepted platform exclusions. A newly generated root lock is a different graph
and cannot certify the Appium CLI's existing physical home.

## Node policy

`scripts/mobile/host-node-trust.mjs` accepts only the complete reviewed bundled
DER set for Node 24.15.0 (145), or Node 22.14.0 (149), and their exact
already-clean equivalents. It removes only emSign ECC Root CA G3, SHA256
`86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b`.
Every other DER is retained. Missing, duplicated, substituted and unknown roots
refuse. The resulting base stores contain 144 and 148 certificates respectively.

`prepareHostNodeTrust` writes a new exclusive private directory, owner-only
0600 PEM and policy, and an owned empty CA directory. The public descriptor has
kind `caseops-host-node-trust-v1` and binds the exact helper/bootstrap bytes,
Node version, complete sets, bundle, role and optional one public fixture CA.
Its authority pair is `CASEOPS_HOST_NODE_TRUST_POLICY_FILE` and
`CASEOPS_HOST_NODE_TRUST_POLICY_SHA256`. It returns a child environment; it does
not change the shell, operating-system store, or current Node TLS defaults.

A trusted outer launcher must read/hash the reviewed helper through its held
FD and execute that retained buffer. It supplies `sourceRefs` to preparation.
The inherited bootstrap is likewise a bounded data URI built from its held
reviewed bytes, avoiding a later helper-path module reopen or Windows spaces.
The Windows provisioner's real outer bootstrap is exercised as Node source by
its colocated tests. Ordinary debug CLI preparation is not an independently
verified producer binding by itself; native release launchers must bind the
actual reviewed source and policy references before private admission.

The exact scoped `NODE_OPTIONS` is `--use-openssl-ca` plus that one derived
bootstrap URI. `SSL_CERT_FILE` selects the bound base PEM and `SSL_CERT_DIR`
selects the bound empty directory. Unknown/system/OpenSSL overrides, TLS bypass,
additional preload flags and npm CA/verification bypasses refuse. The Node test
runner may repeat only the exact approved OpenSSL flag/bootstrap URI and its
compiled default cipher list; changed values still refuse. Node 24's
OpenSSL-mode default getter actually reports zero before activation. The
bootstrap replaces the current thread's defaults from the verified held PEM
before the real npm/Appium/entry import, then requires the exact 144-root getter
set. Node 22 lacks both APIs: it verifies the selected bundle and must use actual
default HTTPS and fetch transport evidence; it claims no default enumeration.

Only explicit `native-qa` may admit one exact descriptor-bound self-signed
fixture CA through `NODE_EXTRA_CA_CERTS`. Base role never accepts it. The QA
policy does not authorise credentials, paid providers, arbitrary destinations or
production use. Normal Worker/subprocess inheritance is tested. An explicit
worker/child env, execArgv or custom TLS `ca` override is outside that proof and
needs its own admission. No universal thread/lifetime/default-agent claim is made.

All loopback verification constructors send
`X-CaseOps-Automated-Test: no-paid-providers`; the server checks the exact value.
Repository fixtures exercise real default HTTPS and fetch: trusted synthetic CA,
unknown CA, and wrong hostname. They do not disable certificate or hostname
verification. Separate synthetic file-only/empty-file controls establish actual
OpenSSL selection without QA EXTRA, and are labelled transport-only. No live
key or enrollment is read. Node 22's selected148 store must not be silently used
as the Python/Ruby127 or Java117 store: cross-runtime children require explicit
neutral rebinding to their independently validated recipe.

## Provisioning and readiness

Run the Windows PowerShell 7 provisioner from a verified checkout. It performs
held-source preparation and actual scoped verification before even npm --version,
then uses anonymous private npm configuration and a fresh per-platform common
root `{core,home}`. No old cache is overwritten. Its 900-second setup contract
clips each public tool child to 300 seconds with cleanup reserve, preserves real
exit codes and bounded stdout/stderr (successful stderr is valid diagnostic
output). Interrupted roots are unknown, retained and never replayed. It signals
only the exact owned root process; it does not claim complete Windows descendant
absence. Actual Windows provisioning and its stronger release process/resource
acceptance remain unrun. `-WithJdk` refuses an unproved .NET download; a separately
verified platform JDK is required. There is no global environment mutation.

The manual macOS npm/Appium commands in older runbooks are graph descriptions,
not permission to bypass this preflight. Launch every actual Node child with the
verified recipe derived by the held outer launcher, never by blindly copying a
logged NODE_OPTIONS value. Require fresh advisory/notice/physical graph evidence
and loopback driver health after arranging each new root.

Use a separate complete common root for each OS. Core plus selected home must
fit the unchanged native capture: two root-present complete inventories,
50,000 charged entries, 512 MiB charged payload and 5 seconds, with final every
path/namespace reconciliation. Driver-to-Appium aliases must resolve inside the
same captured root. Do not capture only core, silently skip a home, follow an
external alias, raise caps or retry a warmed failure for green. Metadata size
estimates do not prove the payload deadline. All-three union exceeds the entry
bound. New path/alias/registration arrangements need new graph/audit/notice
receipts; older hashes are not restamped.

Before native use: fresh complete locked/physical advisory zero; all exact
nested body-parser/shell-quote copies and official provenance/notices; actual
Appium/driver CLI registration; owned loopback health with zero sessions;
current trust policy; full runtime payload capture; and actual source/binary,
backend, device and provider/auth bindings. None is supplied by this document.
# Exact public checksum review after the hosted scan

The hosted tree scan of `df4b299a660e9ab00655054f7f4caf1b28a1f340`
reported the public certifi bundle checksum at line81 of
`scripts/mobile/host-platform-trust.py`. Its35 native findings and34 previously
accepted origins remain retained. The history boundary was not reached.

An independent marked HTTPS read of the official
[certifi2026.10.19 PyPI metadata](https://pypi.org/pypi/certifi/2026.10.19/json)
and its exact `certifi-2026.10.19-py3-none-any.whl` verifies these public inputs:

- Wheel:136,464 bytes, SHA256
  `42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b`.
- The wheel's `certifi/cacert.pem` exactly matches the installed120-anchor bundle:
  `50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785`.
- The complete reviewed source line has SHA256
  `0c3ed116e3a6d25ea71ba6336dabfa79c49fcdea1bc629a17ec6ce0b09637fe4`.

The HTTPS verifier used only the descriptor-held120-anchor bundle, hostname
and certificate verification, no redirects or retries, and the exact no-paid
marker on both requests. No trust store changed. The policy adds only the two
independently verified immutable local/published origin fingerprints. A
repository regression checks the current exact span and ancestral blame;
changed spans, later origins and unrelated findings remain blocking. This
review is not a successful replacement tree/history scan or a release waiver.

The first replacement's complete74 canaries and current-tree scan passed,
but its82-commit local history scan found an earlier representation of the same
official bundle digest. That separate failed history evidence is retained.
The exact additional origin is `2fe2d37cc8623fe91d9e463244a2880469939612`,
line35, with complete-line SHA256
`99aa023b175ad129caccb5840eb31efb84788a510b30f615901ed50c8a371b8c`.
Its immutable source contains the independently verified public bundle hash.
Only this separately reviewed historical fingerprint is added; the successful
tree result does not substitute for a complete replacement history scan.



## Explicit shared Gradle/JDK scope

The Android wrapper keeps real Temurin21 for Gradle9.4.1 and real Temurin17
for toolchain children. The existing `java21` PKCS12 and `java17` JKS recipes
remain separate. Passing the Java21 recipe to the Java17 label is refused.

`prepare_gradle_policy(output, freshPlatformPolicyRef, environment=neutral)`
creates kind `caseops-host-gradle-jdks-trust-v1`, runtime scope
`gradle-java21-java17`. It independently checks both original typed117-anchor
stores, retains Java21's exact PKCS12 bytes in one owned store, and records
`aliasOrigin: java21`. Both pinned JVMs decode those exact retained bytes and
inspect the effective default117 anchors before the policy is published.
A producer diagnostic is written before each result is admitted, including
nonzero children; partial output is retained on refusal.

Call `scoped_gradle_environment(sharedRef, neutralBase,
verification_log=durableRecorder)` before applying the common environment.
The recorder is mandatory. Export freshly checks both original inputs, both
shared-store decoders and both effective defaults; every JVM's stderr and
executable/source/input hashes reach that recorder before environment return.
The result adds one PKCS12 `JAVA_TOOL_OPTIONS` and the policy reference pair.
Node, Python and CMake trust recipes remain separate. No JDK home, executable,
system store or owner configuration is replaced.

`prepare_gradle_qa_policy` is a distinct118-anchor local-fixture derivative.
Only an exact owned fixture receipt can export it. Production remains117.
Actual marked default-client trusted, untrusted and wrong-host controls on
BOTH JVMs are required. Their HTTP deadlines remain3 seconds; each helper's
entire shared deadline remains60 seconds, including retained inputs and logs.
The helper proof does not establish Gradle client/daemon/compiler propagation
or a successful Android build. A separate offline Gradle9.4.1 propagation proof
and the canonical build remain required before native acceptance.

The pinned public API review distinguishes compiler
[ForkOptions](https://raw.githubusercontent.com/gradle/gradle/v9.4.1/platforms/jvm/language-jvm/src/main/java/org/gradle/api/tasks/compile/ForkOptions.java)
and [BaseForkOptions](https://raw.githubusercontent.com/gradle/gradle/v9.4.1/platforms/jvm/language-jvm/src/main/java/org/gradle/api/tasks/compile/BaseForkOptions.java)
from task-specific
[ProcessForkOptions](https://raw.githubusercontent.com/gradle/gradle/v9.4.1/subprojects/core-api/src/main/java/org/gradle/process/ProcessForkOptions.java).
Task-specific environment APIs exist; they do not provide a reviewed uniform
hook for every compiler/plugin worker used by the canonical wrapper. No init
script, generated project mutation or internal Gradle API is introduced here.


## October31 dependency follow-on

The version pins above describe CLI/driver code identity; they do not certify all bundled dependencies against later advisories. Newly affected glob/minimatch copies require the local `glob14.0.2-caseops.1` default-bundle rebuild and the distinct npm11.12.1 dependency rebundle. An override alone cannot repair code already embedded in a minified bundle or an inBundle driver dependency. All existing trust policies and reviewed deepmerge exception semantics remain.

Native CI now uses `node scripts/mobile/npm-tooling.mjs` for normal npm arguments (`../../scripts/mobile/npm-tooling.mjs` from apps/mobile). `--npx` selects the same package’s npx; `--cli-health` checks every production dependency edge; `--audit-cli` sends one marked, TLS-verified current advisory request for all146installed package identities, seven embedded dependencies and the explicit upstream glob mapping. The helper accepts exact Node22.23.4/24.15.0, a fixed local archive digest, fresh private runtime directories and scoped nested launchers. Ordinary npm/npx and nested launchers use the kept marked registry entry without changing NODE_OPTIONS; POSIX kernel executable access is required before CLI dispatch. It does not install or update global npm.

The archive and all149notice members are in `apps/mobile/vendor/npm-11.12.1-caseops-security/`; PROVENANCE.json identifies the13dependency roots/10range fields/accepted launcher change and MEMBERS.json pins every2149member payload/mode. Twenty-four Mac and24 actual Linux22 controls passed, including exact nested CLI identity against a hostile different-version global, native request marker/TLS/authentication/payload preservation, no added replay, kernel noexec refusal and complete root-present paired inventory refusals. Actual Windows acceptance remains pending. New preparation runtimes include the2594-object package root, enclosing root, two scoped launchers, one bin directory, one held entry file and one transport directory (2600objects total); none are claimed to be native app artifacts.

The original Android build failure and backend preparation refusal remain retained. Current native APK/Simulator/device/store acceptance is still NO-GO.

## November 1 Appium driver repair

The official-release rule above can no longer pass: Appium 3.9.0, UiAutomator2 8.7.3 and XCUITest 12.22.2 resolve or bundle glob 13.0.6 and minimatch 10.2.6 (GHSA-3g3m-2fjr-6pw4, GHSA-g3hv-75wg-m249). UiAutomator2 8.7.3 is the newest stable release. The fresh 31 October four-inventory audit failed on exactly these two names, and no Appium runtime was admissible for native use.

`node scripts/mobile/appium-tooling.mjs prepare /absolute/new-runtime` installs one npm project, `scripts/mobile/appium-tooling/`, with Appium 3.9.0, WebdriverIO 10.1.0 and both drivers. One project lets each driver's `appium` peer resolve to the installed core, and one lockfile covers the graph. The runtime is also `APPIUM_HOME`.

- Appium and WebdriverIO consumers use scoped overrides to the reviewed `glob 14.0.2-caseops.1` and `minimatch 11.0.1`.
- An override cannot reach a driver's bundled dependencies. Each driver is therefore rebuilt from its exact upstream archive (pinned sha512) as an openly versioned private `8.7.3-caseops.1` or `12.22.2-caseops.1`, not a disguised official version.
  - The bundled `glob` and `minimatch` are replaced with those fixed packages. `@isaacs/nonrecursive-glob-match` 1.0.3 is added, and `path-scurry` 3.0.0 is nested under glob only.
  - The bundled dependents declare the exact fixed versions: `@appium/support` and `readdir-glob` in both drivers, plus `appium-ios-remotexpc` in XCUITest.
  - Every other upstream member is byte-identical. `CASEOPS-REBUNDLE.json` inside each package records each change.
  - Each replacement must find the exact prior version. Each output tar digest and archive integrity is pinned.
  - Each replacement and each driver must ship its own licence file. The provenance records its licence and file digest.
- Official archives are downloaded from `registry.npmjs.org` with the no-paid marker and verified TLS. Downloads stream under per-archive and total byte bounds and one shared deadline before their integrity check.
- The checked-in lock is installed by `npm ci` through the pinned npm, without lifecycle scripts.
- The locked and complete physical graphs are both audited, including bundled packages and glob's embedded bundle sources. Any advisory refuses.
- The physical inventory requires the root and its `node_modules` to be present.
  - Manifests are read through held descriptors.
  - It allows only `.bin` links to bins their sibling packages declare, npm's hidden lock and Appium's `.cache/appium` metadata. Any other dot entry, link or unmanifested code refuses.
  - Every installed package must match the lockfile and hidden lock. Empty placeholder directories must be optional lock entries. Lock entries that are not installed must be optional and excluded by `os`, `cpu` or `libc` on this host.
  - A final pass re-observes every listing, directory and file. Discovery and reconciliation are both charged to one entry, byte and deadline budget.
- `appium-tooling.mjs` and its manifest and lock are native source-fingerprint and dirty-fence inputs.
- Compatibility of the major updates was checked by API comparison.
  - Glob 14 only widens types.
  - Minimatch 11 removes `makeRe`, `AST` and `matchOne`. The bundled consumers use only APIs it keeps: `readdir-glob` uses `new Minimatch(...).match()`, and `appium-ios-remotexpc` uses `minimatch(path, pattern)` for AFC listing filters.

Local results:
- The two-driver runtime passed with 905 locked and 906 physical identities and zero advisories.
- An isolated Appium 3.9.0 server loaded both drivers.
- The rebuilt bundles resolve the fixed glob and minimatch in place.
- Earlier, a UiAutomator2 session on the 16 KiB API 36 emulator located the real `sign-in` control.

These results show tooling health only, not native acceptance. No iOS Simulator session has used the rebuilt XCUITest yet.
