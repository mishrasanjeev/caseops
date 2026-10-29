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
