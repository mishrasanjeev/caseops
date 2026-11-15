# Native WebDriver isolation — 2026-11-15

J20/M22, US-MOB-01/02/08. **Partially implemented / Partially fixed;
release NO-GO** pending the final frozen-source and actual native gates.
This is a verification-transport defect, not evidence of a paid provider call
or an application authorization defect.

All six native `remote({...})` constructors omitted the automated-test header.
The marker on an independent status client or app fixture did not mark those
WebDriver requests. The six sites cover ten platform variants:

| Runner | Platforms |
| --- | --- |
| `run-native.mjs` | Android, iOS |
| `run-android-files.mjs` | Android |
| `run-ios-files.mjs` | iOS |
| `run-queue-privacy.mjs` | Android, iOS |
| `run-client-extensions.mjs` | Android, iOS |
| `run-v1-workflows.mjs` | Android, iOS |

Each constructor now imports the existing `MARKER`/`MARKER_HEADER` contract
from `apps/mobile/e2e/support.mjs` and sets its own `headers` option. All other
constructor bytes, capabilities, retry-zero settings, transport timeouts,
case IDs, callback/role inventories and qualification gates remain unchanged.
There is no runtime wrapper, new dependency, SDK/device action or audit exclusion.

The three added `tooling.test.mjs` cases independently discover every direct
native constructor and evaluate its actual option expression with the existing
TypeScript parser. They retain all six sites, ten platform variants, caller
capabilities and original transport settings. The complete changed module
passed **469/469**, without skips, failure, cancellation or todo.
The ten other affected modules pass **695/697**, with the same two explicit
Windows-only skips and no failures. Their earlier eight Python/TLS-gateway
setup failures are retained; replay used the unchanged approved pinned-Python
full-gate environment rather than the broken host CLT stub.
All ten canonical platform/family collectors produce complete JSON identical
to the `8000` baseline: **83 intended/discovered cases per platform**. This is
collection proof only. Independent native-reporter reconciliation requires
**1883** full-harness cases: all 1858 old cases, all **22** new iOS qualification
cases and the three constructor cases, with the same three Windows skips.
The earlier 17-addition planning count is superseded; the final whole gate is
still pending and must verify this exact count and every original title.

The explicitly invoked verification fixture uses the actual separately pinned
WebdriverIO **10.1.0** with an owned loopback HTTP peer. Its **30/30** cases prove
received create/read/delete headers, actual capability payloads, and exactly one
POST for both an HTTP create failure and a lost create acknowledgement. It
requires the real tooling; it has no missing-tooling skip or fake client. Run:

```sh
CASEOPS_MOBILE_TOOLING_HOME=/absolute/reviewed/appium-runtime \
  node --test scripts/mobile/fixtures/native-webdriver-transport.mjs
```

This fixture is deliberately separate from the default source-only CI module
inventory, which does not install Appium. It is required before the next native
candidate freeze and is not one of the 83 native cases. Its listener/sockets
have a separate one-second cleanup fence; no native acceptance budget changed.

The retained evidence directory is
`$CASEOPS_NATIVE_RELEASE_EVIDENCE_DIR/m28-native-wdio-marker-repair-01/`:

- `baseline-real-client-02.log`: before the six-site patch, the real Core client
  completed the owned create/read/delete spine but its received marker was
  `undefined`; the focused assertion failed. The earlier package-export fixture
  refusal is retained as `baseline-real-client-01.log`.
- `six-constructor-exact-patch-proof-01.json`: complete before/after source hashes
  and exact preservation of every other constructor/file byte.
- `actual-real-client-matrix-02.log` and its result: all 30 real-client cases pass.
  The initial fixture socket-close-event failure remains in matrix `01`; the
  corrected fixture waits for actual owned socket closure instead of inferring
  it from the listener-close callback.
- `complete-tooling-01.log` and its result: the complete 469-case module passes.

Those runs used the working successor of `10541d74`; final committed source,
whole 21-module gate, current CI/security verdicts, actual APK/Simulator builds
and native/hardware cases still need their own exact evidence. Earlier `8000`
source passes, current retained ordinary member authentication and old builds
cannot be relabeled as the successor's native acceptance.

## Separate host bundletool qualification HOLD

The dated host-tool audit identified dependencies bundled in official
bundletool **1.18.3**: Guava **32.0.1-jre** with
**GHSA-xxph-c9ww-hj94 / CVE-2026-102554**, and jose4j **0.9.5** with
**GHSA-3677-xxcr-wjqv / CVE-2024-29371**, confirmed by the audit owner.
The protobuf-java **3.22.3 / GHSA-735f-pc8j-v9w8 / CVE-2024-7254** finding
is also primary-confirmed: it is below the **3.25.5** fixed range. The selected
official **3.25.9** input has a zero-advisory registry/OSV observation; that is
input admission, not a repaired-tool smoke. The retained primary advisory is
`bundletool-compatibility-20261115-01/protobuf-advisory.json`, SHA-256
`4dbf52014a7fc56acf1731143ad4279bbe531524cf8f45743052487c12505c3b`. These are host qualification-tool
findings; they do not establish that the app ships those Java dependencies.

The repair is an unshipped private host-tool derivative outside this repository.
Its actual advisory closure and smoke remain pending. The source-bound SDK/tool
qualification gate remains **HOLD**; Android's 14 qualification prerequisites
and final 15 submission gates are unchanged. There is no new build, native,
store or distribution credit. Retain the audit owner's immutable plan
`bundletool-compatibility-20261115-01/pending-plan-01.json`, SHA-256
`53d06ddebe9becab895c9f46d80def1ce22717ebc86ce2a5ae37e905ca09bfd9`.
