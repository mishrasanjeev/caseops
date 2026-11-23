# Android supplier repair — 23 November 2026

Release verdict: **NO-GO for the replacement Android release**. Implementation
status: **Partially implemented**. The existing public version 1.0.0 (3) and
its production login diagnostic do not certify this replacement. Neither a new
signed AAB nor full native acceptance is established by this record.

The actual FAF production inspection resolved five Gradle roots and 17
projects. Its two successful offline phases retained 54 used views, 2,409
artifact references, 511 unique Maven artifact paths, and all 135 distinct final
resolution metadata objects. The metadata had 169 notifications; that is not
169 distinct configurations. All 511 payloads matched official verification
metadata. A fresh OSV query of the 510 unique coordinates returned 100 advisory
rows affecting 28 coordinates. Journal budgets and the original failed capture
attempts remain unchanged.

Gson 2.8.6 and Commons IO 2.6 occur in the app's release runtime configuration.
Okio 2.9.0 occurs in compile configurations; the observed app runtime instead
selected Okio JVM 3.16.0. This is not proof that Okio 2.9.0 shipped in the APK.
The remaining affected coordinates belong to build configurations. In
particular, React Native WebView resolved its own AGP 7.0.4 classpath, even
though the build applied AGP 9.2.1. Its old classpath introduced legacy Netty,
Bouncy Castle and Protobuf suppliers. Root and included build configurations
also selected affected Guava and Kotlin plugin versions.

The dependency repair appends a scoped policy to `android-no-paid.gradle`.
Its security suffix remains byte-identical through the separate reviewed
Gradle transition. That transition changes only the exact Gradle version,
the moved transport class import and its three changed JAR origins. The
source oracle reverses those explicit changes and verifies the original
29,310-byte transport policy hash. Exact native code origins, classloader
identity, private-final reflection fields, authentication scopes and redirect
checks remain fail-closed and require actual Gradle execution. It aligns
only WebView's AGP classpath with the applied 9.2.1 version, repairs affected
build coordinates and Kotlin plugin requests, and sets release compile/runtime
minimums for Gson, Commons IO and Okio. Numeric newer selections remain newer;
unreviewed selectors and flavours are rejected. Debug/test configuration rules
and unrelated coordinates are preserved.

Official Maven metadata and fresh candidate OSV queries establish these
current stable candidate minimums: Gson 2.15.0, Commons IO 2.22.0, Okio and
Okio JVM 3.18.2, Guava 33.8.0-jre, Commons Lang 3.22.0, jose4j 0.9.7,
JDOM 2.0.6.1, Kotlin Gradle plugin 2.4.21 and Bouncy Castle jdk18on 1.86.
Candidate publication and empty advisory responses do not establish actual
resolution, Android compatibility, licence closure or release acceptance.

The bundled Gradle supplier also needs repair. The original official Gradle
9.4.1 distribution includes Guava 33.4.6 and Bouncy Castle 1.81. The chosen
replacement is the complete official Gradle 9.9.2 distribution, rather than
modified JARs inside the old distribution. Its official release SHA-256 is
`971fcd7150ca4ba04852c0b2ca0d2d0ab9468e14b03473eab19528809914c76b`.
The retained ZIP and every installed file/mode have been verified against
the official archive (720 files and 350 JARs). Production and QA Expo
prebuilds pin its exact URL and checksum through the same opened wrapper
descriptor; unknown templates, duplicate properties and wrong checksums
are rejected. Complete supplier advisories, actual Gradle compatibility
and rebuilt APK verification remain separate gates.

The JDK supplier refresh separately selects official Temurin 21.0.13.1+2
and 17.0.21.1+2. Both macOS ARM archives and installed files have complete
publisher-checksum, byte and mode reconciliation. The Windows installer pins
use the corresponding official Windows x64 URLs and checksums; those archives
have not been installed or accepted on this Mac. Previous JDKs and policies
remain preserved.

Both new vendor trust stores contain exactly 117 unique public certificates,
exclude the denied root, and have set SHA-256
`cef81225c6ee4493b78527f09fc422ee50d5160feb4d8b8c0b334b4ef5c0180f`.
Their exact set changes four removed and four added roots relative to the
previous cleaned set. The new helper admits that exact vendor set, not merely
its count; its negative control rejects the earlier equal-count set. Global
stores and personal-device trust remain untouched. The complete five changed
Node modules passed 681 cases with two declared Windows skips (683 total),
and all 49 host-platform Python methods passed with independently reconciled
native identities. The original 50-percent prechild refusal is retained;
this pure control replay used the separate approved light-unit class. Actual
new-JDK shared-store and Gradle execution remain distinct required proofs.

The original 510-coordinate result is not a complete SDK audit. Supporting
origins additionally contain 21 Maven plugin/compiler suppliers and six local
included-build plugin outputs. These, all used bundled Gradle tools, exact
licences and native observer compatibility must be reconciled before signing.

Evidence is retained under the native release evidence root
`native-release-20261111-ZzEIol4V`, in:

- `current-android-production-inspection-faf7be8f-preparation-01/sdk-used-two-phase-actual-08`:
  actual successful graph capture and complete metadata reconciliation.
- `current-android-production-inspection-faf7be8f-preparation-01/sdk-supplier-actual-02`:
  official payload hashes, fresh advisories, exact native owner scopes and
  dependency parent paths.
- `current-android-production-inspection-faf7be8f-preparation-01/latest-stable-maven-policy-01`:
  official metadata and fresh changed-candidate advisory queries.
- `official-gradle-9.9.2-qualified-input-01`: official replacement distribution.

The complete local tooling module passed 477 cases with no failures or skips.
The updated build configuration module passed 101 cases; its two declared
Windows CLI cases remain skipped on this Mac. The complete Android wrapper
module passed 49 cases. All three requested modules were present in the
native reporter; 629 cases comprised 627 passes and those two skips.
A first fresh-checkout run lacked root Next dependencies, and a later new
positive fixture used an incorrect JavaScript escape. Both failures remain
retained; the complete three-module replacement passed after canonical
root installation and correction of that fixture. Ten independent Groovy policy contract
controls passed under the qualified official 9.9.2 distribution. The complete
replacement control invocation exited zero with verified process-group
cleanup and unchanged observation/byte budgets. The first invocation's ten
body successes and failed postflight observation bound remain retained as an
incomplete invocation. These controls use API-shaped Gradle doubles; they are
not actual Android dependency resolution or native app acceptance.

The first actual 9.9.2 online preparation passed the marked transport and
patched-JDK checks, then failed in React Native's Kotlin plugin request.
Gradle compares the original declared request even after `useVersion` changes
the displayed version: the installed catalog still declared 2.2.0 while the
classpath contained 2.4.21. The failed invocation and its cleanup are retained.

The next candidate adds an Android prebuild declaration overlay for exactly
five integrity-pinned vendor files: React Native's Kotlin catalog, the Expo
autolinking root and serialization plugin declarations, and the Expo launcher
and modules-core plugin declarations. All preimages match the official npm
archives. The overlay admits all inputs before replacing any vendor file,
transfers descriptor-verified buffers through private staging, accepts the
exact known result on replay, and refuses unknown inputs. Runtime sources,
package manifests and bundled notices are unchanged. The same Android mod
applies this projection to production and local QA. Actual Gradle regression,
complete repaired resolution and native acceptance remain required; this
overlay does not bypass Gradle's version tracker.

The complete seven affected and adjacent Node modules passed 728 cases with
two existing Windows-only skips (730 total). All nine new overlay controls
passed, including a simulated Windows named-device-zero exception that still
checks the full descriptor device and nonzero named devices. This simulation
is not actual Windows acceptance. The earlier environment-incomplete wrapper
replay and the device-comparison regression's red result remain retained.
The actual Expo mod compiler replay covers both QA and default cleanup.

Remaining acceptance: resolve the repaired graph on the actual candidate,
close every supplier and notice
inventory, rebuild the release APK/AAB, execute the complete 83-case/249-phase
Android native inventory with independent hardware checks, and complete every
store qualification and promotion gate. Do not transfer FAF binary, backend,
Simulator, JavaScript or public-version evidence to a changed Android binary.

The earlier native producer and local-run preparation guards require the
binary, API and Web commit identities to match. Later fixture fields that
record these identities separately do not override those guards. The final
repair head therefore needs canonical API and both platform Web builds and
qualified backend epochs, together with matching rebuilt native artifacts.
Unchanged scoped source fingerprints do not authorize relabelling old images
with a new commit.
