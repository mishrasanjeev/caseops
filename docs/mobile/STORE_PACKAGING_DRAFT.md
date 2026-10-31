# Store packaging preparation draft — 2026-10-27

This preparation started as an isolated draft at commit
`48f201ef056666cd0540bf442f63fb382e4bce40` and is now included in the working
candidate with its CI and production-config fixture integration. The retained48
QA source,118-input fingerprints, installed apps, ledgers and reports stay
separately bound to their original source; they do not certify these changes.
No enrollment, key creation, agreement acceptance, payment, upload or publication
is performed. The required mobile dependency audit remains NO-GO with four HIGH
entries; this preparation is not a waiver or a release verdict.

## Deliberate preparation boundary

Camera development after Today `f5d95426` adds explicit one-image capture with
Expo ImagePicker58.0.10/ImageLoader58.0.3 (MIT), an optional camera permission
purpose and app-private SDK copies. Its encoded metadata can include capture
location even though CaseOps requests no location permission; `exif:false` is
not a byte-sanitization guarantee. Store privacy/Data safety drafts must cover
the uploaded photo content/metadata and actual SDK processing, plus the owned
cache lifecycle described in `NATIVE_DATA_INVENTORY_2026-10-27.md`. Reconcile
actual release permissions, supplier manifests and physical camera behavior
before submission. No new store acceptance or zero-location claim is made.

Optional biometric screen lock uses the existing SecureStore 58.0.2 with a
specific Face ID purpose string and device-only policy/protected marker. The
app receives protected-storage authentication outcomes, not biometric templates.
Server MFA/revalidation remains mandatory. Include the local linked identity
metadata and OS handling in privacy review; physical enrollment, backup,
uninstall, permissions and actual artifact acceptance remain pending. See
`BIOMETRIC_SCREEN_LOCK_2026-10-27.md`; no compliance claim follows from this UI.

`prepare-store-packaging.mjs` accepts only `--plan`. `--run` and unknown modes
refuse before reading inputs. Output is always `preparedOnly:true`,
`readyForBuild:false`, `executionEnabled:false`. It produces immutable public
input snapshots, command arrays, and an ExportOptions or Gradle signing projection.
It does not execute those commands, read a keychain/keystore, install a profile,
download dependencies, or claim a valid signed artifact. A reference to signing
material is not evidence that the material exists, belongs to the publisher,
has an accessible private key, or can sign the requested app. Synthetic mode
exists only for bounded offline contract fixtures and cannot enable execution.

The plan-only CLI remains reviewable preparation. The current source also
implements a separate guarded local execution entry point,
[`run-store-packaging.mjs`](../../scripts/mobile/run-store-packaging.mjs), with
an explicit `--execute` request and reviewed GO. Its
[`store-packaging-execution.mjs`](../../scripts/mobile/store-packaging-execution.mjs)
consumer checks the complete current gate inventory, exact tools and source,
actual store-history inputs, signing admission and artifact postflight. This
implemented path does not establish that a real distribution-signed IPA or AAB
has been built or verified. Those artifacts and store acceptance remain
unverified; do not copy a plan into an unreviewed shell or treat an unexecuted
compiler/archive command as a successful release.

## Immutable build numbering

Production link configuration now additionally requires the following public
store-build file/hash pair. Local QA retains `0.1.0`, SDK-default build metadata,
the existing explicit callback and profiles. QA refuses mixing store metadata.

`CASEOPS_STORE_BUILD_FILE` is an absolute canonical regular JSON file and
`CASEOPS_STORE_BUILD_SHA256` is its exact lowercase SHA-256. The reader checks,
hashes and reads through one descriptor, closes on every path, rejects symlinks,
changed identity/metadata, malformed UTF-8/JSON and unknown fields, and never
reflects malformed JSON contents in its error. Maximum JSON size is64KiB. The
descriptor read itself consumes at most that limit plus one detection byte,
including growth after the initial stat. POSIX files must have the current
owner UID and exactly one link. Windows keeps inode identity, compares devices
only where portable, and rejects multiple links when reported; real Windows
acceptance is still separate from these Mac controls.

The complete build schema is:

| Field | Contract |
|---|---|
| `schemaVersion`, `kind` | `1`, `caseops-store-build` |
| `syntheticDataOnly` | Boolean matching the link input and baseline; production rejects true |
| `nativeLinkConfigSha256` | Exact digest of the same immutable production link input |
| `identities` | Exactly `iosBundleIdentifier`, `androidPackageName`, matching that input |
| `version` | Three numeric marketing-version components; no implicit version, rollback or0.0.0 |
| `iosBuildNumber` | Explicit string integer1–9999, a deliberately conservative draft policy |
| `androidVersionCode` | Explicit integer1–2,100,000,000 |
| `baseline` | Exact `{path,sha256}` reference to the declared baseline |

The baseline has exactly `schemaVersion:1`,
`kind:caseops-declared-store-build-baseline`, `syntheticDataOnly`, the same
`identities`, `marketingVersion`, `iosBuildNumber`, `androidVersionCode`, and
`scope:operator-declared-not-store-verified`. A baseline counter may be0 for a
declared first release. Both proposed counters must strictly increase; the
marketing version cannot decrease. This proves arithmetic against those exact
declared bytes. **It does not independently read or certify either store's
maximum.** The person preparing the real release must reconcile the actual
store history and concurrent release work first.

`reserveBuildNumbers` supplies an exclusive, shared-directory reservation
primitive. It is not called by the plan-only CLI. The eventual runner must call
it before reading signing secrets or starting a build, use the same canonical
owner-private reservation directory for every invocation, and retain partial or
failed reservations. Reordered identity-object keys cannot bypass collisions.
Each reservation keys the platform and that platform's application identity,
so changing the other platform's ID cannot reuse an already reserved counter.
Choosing a different directory is not a global store-history proof.

## Recipe request and immutable identities

The request has exactly `schemaVersion:1`,
`kind:caseops-store-packaging-request`, `preparedOnly:true`, `syntheticDataOnly`,
`platform:ios|android`, `source`, `nativeLinks`, `storeBuild`, `apiOrigin`,
`webOrigin`, and `signing`. `source` contains the exact current `sourceSha`,
`sourceFingerprint`, and `inputFileCount`. Non-synthetic plans require a clean
committed tree. Both origins are explicit canonical HTTPS origins; web origin
must own the configured exact callback. Build settings, API/web origins and link
policy are explicit environment entries, with no acceptance marker or profile.

The iOS signing block requires `teamId`, `applicationIdentifierPrefix`,
`certificateSha1`, `certificateSha256`, `provisioningProfileUuid`,
`provisioningProfileEvidence`, `developerDirectory`, and `podfileLockEvidence`.
The application-identifier prefix must equal the link input. It is **not**
assumed equal to Team ID. Certificate/profile references still require actual
CMS/certificate/private-key/profile verification before activation.

The Android block requires `uploadKeystoreEvidence`, `uploadKeyAlias`,
`uploadCertificateSha256`, `appSigningCertificateSha256`, `androidSdkRoot`,
`javaHome`, `java17Home`, and `gradleUserHome`. The app-signing certificate must
match the link input. The upload certificate is separate: Play App Signing may
use a different app-signing key. Passwords are forbidden request fields and
never occur in argv or generated signing source. The future guarded runner must
obtain `CASEOPS_UPLOAD_STORE_PASSWORD` / `CASEOPS_UPLOAD_KEY_PASSWORD` through an
approved secret boundary and verify the actual keystore certificate/alias.

There are no example production IDs, Team IDs, certificate digests, credentials
or guessed owner defaults in this document. Tests use explicitly scoped public
synthetic fixture data; their structural acceptance does not prove ownership.

## Prepared native command boundaries

The iOS recipe uses no-install Expo prebuild, `pod install --deployment
--no-repo-update`, the device SDK `iphoneos`, destination `generic/platform=iOS`,
Release/manual signing, an explicit archive path and exact version/build/ID.
It then exports the archive with `method:app-store-connect`,
`destination:export`, explicit profile/certificate/team, and
`manageAppVersionAndBuildNumber:false`. No automatic provisioning updates or
upload command is generated. The exact accepted Xcode's export schema and the
profile/certificate entitlements must be checked before execution.

The Android recipe uses the release `:app:bundleRelease` task, not a QA APK task.
It supplies a separate Gradle signing projection through an init script; the
release type receives the explicit upload signing config and remains
non-debuggable. Gradle offline mode and SDK/JDK auto-download refusal are
explicit. This init projection is draft code, not a compiled AGP integration
pass. Its behavior against the pinned actual generated native project remains
unverified until a reviewed build can run with real inputs.

## Required activation/postflight work

1. Complete the candidate's full frozen-source checks and matching native
   rebuilds/inventories. The20th tooling module, production metadata fixtures
   and isolated native-build fixture closure are now included. The isolated
  21-test result and earlier18-test provisional result remain historical;
   neither certifies the integrated candidate or an actual distribution-signed artifact.
2. Complete all required security gates, independently reconcile real version
   history, reserve both numbers once, and verify clean full source/dependency
   closure and exact accepted tools before signing-secret access.
3. Verify the actual App Store profile/certificate/TeamIdentifier/application
   prefix, expiry, distribution type, entitlements and exact accepted Pod lock;
   or actual Android upload-keystore alias/certificate and final release signing
   projection. No key generation or account provisioning is part of the recipe.
4. Build/export once under finite process/child-cleanup deadlines; retain every
   failure. Inspect actual IPA/AAB metadata, signatures, IDs, version/build,
   embedded policy/source, minimum OS/target/ABIs, icons, privacy manifests and
   notices. AAB signing is a JAR-signing boundary; APK-only apksigner evidence
   cannot substitute for it. An eventual bundletool input must be official and
   pinned before artifact validation; this draft installs none.
5. Verify deployed API/web registries and served association bytes, correct
   application identifiers/certificates, strict TLS and production HTTPS
   handoff on actual signed supported devices. QA Simulator/debug-key receipts
   cannot certify that boundary. Review real privacy/support/account lifecycle
   and complete current intended native acceptance separately.

Official references: [Apple archive preparation](https://help.apple.com/xcode/mac/current/en.lproj/devf37a1db04.html),
[Apple export options](https://help.apple.com/xcode/mac/current/en.lproj/deva1f2ab5a2.html),
[Android command-line release bundles](https://developer.android.com/build/building-cmdline),
[Android versioning](https://developer.android.com/studio/publish/versioning),
and [Play app version limits](https://support.google.com/googleplay/android-developer/answer/9859152).
