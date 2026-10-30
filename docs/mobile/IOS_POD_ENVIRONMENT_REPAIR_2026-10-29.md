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
