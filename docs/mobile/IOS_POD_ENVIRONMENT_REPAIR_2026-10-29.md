# iOS CocoaPods environment repair — October 29, 2026

J20/M22 remains partially implemented; native release is NO-GO. The A8 native
attempt completed Expo iOS prebuild, then CocoaPods failed at Expo autolinking
with `IOS_HOST_UNREVIEWED_ENVIRONMENT`. Source/runtime/Git postflight passed and
owned foreground groups closed. No Pods, Simulator app or native journey pass
is claimed from that attempt.

A bounded read-only evaluation of the actual generated Podfile reached the
first autolinking constructor and stopped before dispatch. It captured four
previously unreviewed environment names: `EXPO_USE_PRECOMPILED_MODULES`,
`EX_DEV_CLIENT_NETWORK_INSPECTOR`, `RCT_USE_PREBUILT_RNCORE` and `RCT_USE_RN_DEP`.
Their finite values are grounded in the retained generated Podfile/properties
and installed Expo/React Native sources. No environment values or credentials
were captured. Earlier diagnostic transport/read-mode failures remain retained
as incomplete and do not establish that boundary.

The host now preserves exactly these four public switches. The three native
dependency switches accept only `0`/`1`; the inspector switch accepts only
`true`/`false`. Validation precedes the ordinary build-name allowlist, so adding
a name there cannot bypass its value check. Existing owner, trust, proxy,
deadline and unknown-name controls remain unchanged. The canonical simulator
shell entry was regenerated with the new helper's exact hash and size.

Stable regressions:

- IOS-ENV-01 exercises the observed Pod-to-Node autolink argv through all sixteen
  valid flag combinations, retaining scoped CA/policy/deadline and the inherited
  Ruby, CocoaPods, curl, Git, Xcode and neutral constructor roles.
- IOS-ENV-02 rejects invalid values, case variants, unknown siblings, a build-name
  bypass and unsafe cross-role trust overrides before child dispatch.

Both focused cases and the complete tooling file passed (381/381). The complete
33-module functional inventory then passed 1,264/1,266, with exactly the two
existing Windows-only skips and zero failures, cancellations or todos. Actual
exit 0, unchanged source during execution and owned group closure were checked.
A separate Mac check used the actual updated helper, accepted tools and fresh
BASE144/Ruby188 policy to admit the observed constructor; it started no Pods,
Ruby, HTTP or native child.

Evidence is retained in the task cache under
`ios-pod-autolinking-policy-fix-01`, `ios-pod-autolinking-env-diagnostic-05` and
`root-native-contracts-functional-24`. A coherent fresh source/backend binding,
actual Pods replay, generated-tree audit, Xcode build and complete 83-case iOS
inventory remain required. Independent CI's PostgreSQL export work-bound failure
on `108a2215` remains failed and is not waived by this tooling repair.


## QA18 — React Native Pod-to-child environment admission (October 30, 2026)

J20/M22 and native release remain partial/NO-GO. The user story is to prepare a standalone iOS app so the complete document/workflow acceptance inventory can execute. The e7dc engineering attempt passed Expo prebuild and the first autolink, then failed at the deeper React Native dependency/core/codegen boundary with IOS_HOST_UNREVIEWED_ENVIRONMENT. Its source fingerprint is 17193d7051a33f04a8d536bdae1de243a5837978f4c7182d82491e607367c2ea; source/runtime postflight and known foreground group closures passed. Pods completion, Ruby TLS, Xcode, Simulator trust and all83 native cases remain unverified.

The bounded diagnostic executed the exact six generated-Podfile and twelve pinned RN ENV-assignment statements in admitted Ruby, then used the unchanged I62 constructor. It proved ten rejected names: two source paths and eight flags. APP_PATH was the generated raw ios/.. form; REACT_NATIVE_PATH was canonical. It retained only fixed key names and enum/path booleans. No complete Podfile, SDK cleanup, download, codegen, Q mutation or provider action ran. Attempt01 failed before Ruby because multiline diagnostic argv violated the unchanged command-domain fence; it remains incomplete. The corrected diagnostic used a separately scoped private policy; the old expired policy and failed native attempt were not renewed or relabeled.

The repair preserves the earlier four switches and adds only the eight finite SDK flags. Hermes0 is a source-proven early generated-Podfile option; Fabric and New Architecture accept only1. The two paths require a lazily reviewed policy source root, actual owned canonical source/ios/RN directories, unchanged helper bytes and unchanged namespace. Foreign roots, aliases, symlinks and changed source refuse. The adjacent Xcode586-name inventory includes REACT_NATIVE_PATH; the second exact physical-relative spelling is admitted only after owned non-symlink Pods exists. No arbitrary path normalization or build-name bypass is allowed. The canonical shell pins the new helper bytes.

IOS-ENV-03 covers64 valid layouts across all seven composed roles; IOS-ENV-04 covers finite-value/case/build-name/trust negatives; IOS-ENV-05 covers exact path/foreign-root/alias refusals; IOS-ENV-06 composes real POSIX source/directory review with command projection and rejects symlink or changed-helper fixtures. Windows exercises the explicit POSIX refusal; this does not claim Windows iOS execution. The impacted complete subset passed44/44 and the complete tooling module passed385/385 with zero failures, skips, cancellations or todos on accepted Node24/BASE144. The prior381 module cases are retained; four new source-contract cases were added. CI and the independent build-config/source-observer inventories already select the same33 modules, including tooling; module/native83 inventories do not change. Final whole-inventory reconciliation after the separate permanent observer integration remains required.

Raw functional checks: /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-rn-source-policy-repair-qa18-01/checks.json SHA256 34aa69836d06a3e3717e75d1e9a76e712c5e29c9a2258d6a95aa3db4422f7ff4. Original failed native receipt: 4d6fe9e980ddea2665c7eddac3fe6852154a3b7343048630f9cc786b42defabd; diagnostic02 result: 475a92e4877bdfbb3776fe21f8f53c79ad994bfea7239d5f0ffa5955a85641fd. These are scoped source/functional proofs, not complete source-observer or native acceptance. Q remains e7dc until a separately admitted complete source advance; actual repaired Pods/Xcode/device replay and independent Android acceptance are still required.

## QA19 — Preserve typed Node code operands through CocoaPods (October 30, 2026)

Status: source/functional repair verified; native/store release remains **NO-GO**. PRD J20/M22; regression IDs **IOS-ARGV-01** and **IOS-ARGV-02**. The original QA18 native prefix on local8dc02f3 (fingerprint dbfe98ce9517827acbfc664fa12f03a3e0e3c06bed0d90c8691c034db5e6a8ea) passed autolinking, React Native Codegen and the two checked core-artifact downloads, then failed ReactNativeDependencies.podspec after its Node resolver command was rejected. Retain that failed prefix cdfcf346565e30b83a6ecc81a87443dfbf805e0af9f237b7da0220611307800c and its complete source/owned cleanup proof; neither Codegen completion nor downloaded archives are Pods/Xcode/device acceptance.

Actual source-pinned Ruby production of the resolver argv confirmed a line-feed inside the Node `-p` code operand. Unchanged I63 rejected IOS_HOST_COMMAND_DOMAIN before any policy read or SDK Node dispatch; diagnostic 26d67524dca7e3900471652cab8ca99fa3a2bb1a3771349b061bcc44f9ee2f09 retained the exact argv hash and three closed owned phases. The podspec swallowed that rejection and entered its unrelated fallback, producing the missing node_modules/package.json error. Existing React Native package metadata was valid; no SDK file, package metadata or dependency was modified.

The host now admits CR/LF only in the typed CODE operand immediately after the first Node option -p/--print/-e/--eval. Original argument bytes and Promise behavior are preserved; non-code paths/flags, every other executable role, environment checks, NUL rejection, 8192-byte per-argument and 256-argument/2-MiB maximum bounds remain. Ambiguous code options before -- refuse; literal arguments after -- retain their prior meaning. Canonical shell entry was rendered from the new helper and hash.

Actual focused **46/46** and complete tooling **387/387** passed with zero failure/skip/cancellation/todo; both JavaScript syntax checks and shell syntax passed. Preserve the first focused45P/1F 7a1f1044327bae5f2fb58a47377d73f2cb7f75566f08e96deb1005aee4ffcd49: the new test initially expected a generic environment error instead of the unchanged typed rejection; only that new oracle was corrected. The exact Ruby-produced SDK program then passed the new validator unchanged and resolved the existing React Native index.js through actual Node24.15.0 with exit0, no SDK import/network/fake metadata (9064be377e19eed2d00230b8da80708e9e475813ff4875e9f93d6bf6116358d4).

Checks: /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-rn-argv-repair-qa19-01/checks.json SHA256 eccd50f79e1a2522bdbc5d77c1407106ac7b8b83e8104d6b6a2f1b846a549b41. These are functional/source-pin proofs, not complete source-observer or native acceptance. Two new case identities bring tooling385→387; the same33 source modules and native83-per-platform inventory remain. Root's pending permanent-eight tooling integration must retain all QA18/QA19 cases and independently reconcile Python/frontend/CI counts. Q remains engineering8dc until a separately admitted complete source advance; repaired Pods, full generated audit, Xcode and Android/iOS device acceptance remain pending.

## QA20 — Compose OpenURI default stores with the retained Ruby trust policy (October 30, 2026)

Status: source and actual Ruby/OpenURI/TLS regression component verified; native/store release remains **NO-GO**. PRD J20/M22; Ruby OPENURI-01..25 and source/projection IOS-RUBY-01/02. Preserve failed public3b18 native prefix 32fd3a5af7fa3840b6c7bfb1e13596d7ffb93c618699384744b3ac127e41a450 (fingerprint364a90b63ad8efe72641ef6f927062918c1219d85e0b0a8bcd12253c8c735be2): Codegen, ReactNativeDependencies and Hermes downloads/checksums passed, then CocoaPods CDN detection failed IOS_PODS_NET_HTTP_STORE_REFUSED. No Pods/Xcode/device completion is inferred.

Actual source-pinned CocoaPods manager/OpenURI diagnostic a6392c74d87a308ea01444208e581d693286f5e973ba68d7138b59b0c051076d stopped before NetHTTP guard/connection. It proved a fresh non-nil store, distinct from both the policy-owned store and SSLContext default; ca_file/ca_path profiles were already acceptable and VERIFY_PEER was set. Source-pinned OpenURI87056fcf creates that store at331..343. No unknown store was admitted by the diagnostic and no HTTP request was sent.

The host now gives the unchanged OpenURI method a fiber-local per-call receipt for the pinned default-CA HTTPS/no-proxy profile. Its exact source assignment, HTTP identity, host/port, store identity, fiber, policy-owned store and live scope must match. Incoming OpenURI stores are never used for TLS: the existing descriptor-verified policy store replaces them before connection. Unknown direct stores still refuse at START (assignment outside a profile is not a global setter fence); custom CA/unsafe verification/version options, proxy/client-auth and marker overrides remain refused. Peer/hostname checks, every existing root, source/namespace checks, request payload/auth/header behavior, original return/Error identity and60-second production maxima remain. Nested and exceptional paths restore their prior receipt; closed receipts cannot authorize reuse.

New durable scripts/mobile/ios-host-pods.test.rb has an independently collected **25-case/75-phase** inventory. Actual accepted Ruby4.0.9 executed all75 phases successfully, including genuine loopback TLS, unknown CA and hostname rejection, nested success/rejection, fiber/thread separation, same-host wrong HTTP identity, same-HTTP closed receipt, client-auth refusal, original error/return identity, redirects and explicit retry. All17 received HTTPS GETs had the exact no-paid marker; both owned command groups, all TLS server threads and paired source/output inventories closed. No private key was written, no SDK or Q source changed and no external request ran. Acceptance /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-openuri-store-repair-qa20-01/actual-ruby25-acceptance.json SHA256 56b7e2c3d3900ec7432354a39b5bf53c6ba4717be8323408f9e3685d63a79ea2; actual result c2c29f71de152851056db8b94c34e84365941a827ef5cf436a4e024f0b817339.

Ordinary Node CI does not execute this Ruby fixture. Its two independent inventory/retained-stdin projection contracts are handed to Root for merge with the concurrent Windows repairs; complete Node verification and final source reconciliation are owned by Root after all writers close. The new Ruby source must be explicit in isolated snapshots and canonical LF attributes. Actual Appium83-per-platform inventory is unchanged. Complete source adoption, actual CocoaPods CDN/Pods replacement, generated-ios/Pods/SPM audit, Xcode and Android/iOS acceptance remain pending; the original failed native run stays failed.


## QA27 — Transfer only reviewed local Expo SDK archives (October 30, 2026)

Verdict: **Inconclusive for native build and release acceptance**; the private actual host-CLI transfer component is verified. PRD J20/M22. User story: the iOS build operator can consume the exact locked Expo precompiled module bytes already installed on the workstation without admitting arbitrary file URLs, disabling TLS or changing the SDK. Tests IOS-ARCHIVE-01..04 and ARCHIVE-01..08; the native inventory remains all83 cases/249 phases per platform.

Preserve actual bc834 Pods05 failure c4820a23edc9719453e48a595bb69be5975abd9881cb9c935baf7ba5bf295eff, source fingerprint604dd9eee9007c9f1cd8c3348518b6fe81235fdb3790f755159390c7ada27d2c. Expo prebuild, Codegen, React Native/Hermes downloads/checksums and actual CocoaPods CDN/trunk addition passed. Installing ExpoFileSystem58.0.13 then reached the real precompiled-module file URI and refused IOS_HOST_HTTPS_DOWNLOAD. That failed run remains failed/incomplete; its separately scoped complete physical-output diagnostic b8bd05082473ca3a5cc97c73ac820c874f9a85a331329a93f62ac62520fdf895 does not turn the original integrated resource closure into a pass. No Xcode/Appium run or Podfile.lock completion is inferred.

The narrow host repair adds a finite local-transfer family separately from the unchanged ordinary HTTPS curl validator and transport. All10 catalog archives (45,025,306 bytes, four exact package identities) and package manifests match members of already-cached official locked npm tarballs; provenance958cf332e71cdfe620df14364687b9bc5f0cd83ac796372d42529aa2f0424f11. Existing package licenses/notices are unchanged and no dependency or installed SDK was patched. Admission binds the mobile lock, Expo producer source, manifest and exact archive through verified descriptors, rejects URI aliases/traversal/hosts/unknown archives and transfers the retained verified buffer. An absent destination uses EXCL; an existing destination must be empty, owned, regular and single-link. The same descriptor is used for write/readback, source/target replacement refuses, original Error identity survives, buffers are cleared and no curl child is spawned for this family.

Actual accepted Node24.15.0 executed the durable private CLI fixture with **8 cases/24 phases passed**,13 real iosHostCli invocations,0 actual children and0 HTTP requests. Both positive archive families, existing-empty/absent destinations, source replacement before and during write, target symlink/hardlink/replacement, unsafe URI/arguments, changed archive/manifest, Error identity and unchanged HTTPS routing passed. All3 owned groups, paired source/runtime and complete output inventories closed; composed2786 entries/467,627,064 bytes remained below20k/1GiB, canonical7.7924s and observed external16.0099s below30+30. Acceptance /Users/sanjeevkumar/.cache/caseops-mobile/native-end-to-end-20261028-01/ios-local-sdk-archive-repair-01/actual-cli8-acceptance.json SHA256 7aa860ca7d300921886abc794ec7052fd18bae0e951b21155b9e743e0ef1975b.

Retain private attempts01/02 as prebody/prejournal fixture refusals (missing canonical query worker; omitted policy extent), and03 as7P/1F where the replacement fixture's write-only open was miscounted as a source read. The replacement observer counts every read-capable open including O_RDWR/r+/w+, excludes only known write-only opens, preserves the exact-one-read assertion and exercises both replacement branches. No helper or work bound was relaxed to make these controls pass.

Ordinary Node CI runs four portable catalog/projection/inventory regressions and explicitly proves the POSIX refusal on Windows; it does not certify the Mac-only transfer fixture. The new runner must be included in the actual test-source snapshot and canonical LF attributes. Root integrated the exact implementation, canonical shell and durable fixture, then the complete current399 tooling cases passed with zero failures/skips/cancellations/todo. All393 earlier actual case identities are retained plus the2 Android CDN and4 iOS archive cases; source hashes matched after execution and canonical shell render equality passed. Functional combined checks: native-followup-combined-399-01/checks.json SHA256395f8993690902f67512c2196c7cb744234966829e445bc8ad7d2cffc61a83aa. Clean source publication/adoption, complete measured source, fresh Pods replay, independent physical ios/Pods/SPM audits, Xcode build and every Android/iOS UI case remain required. Camera hardware, biometric hardware/signing and verified HTTPS domain boundaries remain separately unverified; no case is silently filtered or counted passed.
