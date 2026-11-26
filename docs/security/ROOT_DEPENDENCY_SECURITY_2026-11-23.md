# Root dependency security repair — November23,2026

Verdict: Partially fixed. The targeted local dependency checks pass; current
hosted CI, the rebuilt public-content browser journey and the complete release
qualification gates remain separate requirements. No signing, upload or store
submission is authorized by this record.

This candidate retains deployed main66f687380dda and all five FDD native-tooling
commits. It replaces Vite8.1.6 with8.2.6, Rolldown1.1.5 with1.2.19 and Undici7.30.1
with7.30.2. Vite requires newer PostCSS; the scoped8.5.26/Nanoid3.3.18 override
preserves the already-safe Nanoid version. Canonical npm resolution produced403
lock records, including16 Rolldown platform bindings, required WASM suppliers,
and Vite's separate LightningCSS1.33.0 branch. The unrelated top-level Rolldown
pluginutils prerelease and other dependency versions are preserved.

Fresh marked primary reads retained24 Vite,61 Undici and6 Napi maintainer
advisories plus exact official registry metadata. Vite8.2.6 is outside the24
published affected ranges. Undici and Napi metadata contain three broad-range
inconsistencies; their explicit patched7.x/3.x declarations and retained fixed
source resolve the selected versions, rather than pretending every literal
range excludes them. Rolldown's JS and Darwin archive provenance point to the
same source commit with Napi3.15.0. The installed Darwin native module's exact
SHA-256 f7624c9163c8b8e4c6997ac94764c48d6e8630844a975ff4c661980531c623e9
matches the verified official archive. This is not a claim of independent
Sigstore cryptographic verification or Linux/Windows native execution.

Canonical root ci passed in9.159seconds. The full lock audit reports zero
advisories at every severity; the installed dependency tree and private CLI
health report no problems, and the private CLI advisory response is empty.
The descriptor-held physical walk independently reconciles307 logical entries
and306 unique package manifests to the current lock, including the workspace's
own nested packages, with final path/metadata fences. Source and lock inputs
remained unchanged during these commands.

The complete new parser module passes9cases. Seven exercise actual Vite hooks
or native Rolldown code generation with ordinary quoted module-name data;
generated JavaScript is parsed by V8 and TypeScript and is never executed. An
initial7pass/2fail report is retained: both failed assertions expected separate
string literals after the compiler had folded an error message. A bounded
literal projection proved each complete peer and parent name remained within
one decoded literal. Only that native optional-peer oracle was corrected;
syntax checks, complete names, cleanup and all9titles were retained. The
complete replacement reports9pass/0fail/0skip/cancel/todo. Web dependency
security5cases and notice32cases pass, as do Next type generation and complete
web/E2E TypeScript checks.

The17 public components contain23 byte-preserved notices. Official Vite,
Rolldown and Undici archives were checked against current registry SHA-512
integrities before their descriptor-verified buffers were transferred. Both
Undici licence texts and Rolldown's full third-party text are retained. The
historical19 managed-SaaS licence review entries are unchanged; supplemental
build-tool source maps now cover79files,104 upload materials and80 operator
materials under the existing namespace/byte bounds.

LightningCSS remains a conditional supplier finding, not a globally repaired
library. The actual release PostCSS configuration invokes Tailwind4.3.0 with
no custom transformer/visitor/resolver; its fixed typed constructors call
LightningCSS1.32.0 with CSS buffers and generated scalars. Vite's separate
1.33.0 dev branch is not a substitute for that build path. No malformed
recognized BigInt/callback path was identified in the reviewed callers. An
ordinary current CSS build is still required; no malformed native input was
sent, no broad supplier waiver was made and no unrelated guard or SDK upgrade
was included.

Actual evidence is retained beneath root-dependency-security-20261123-01:
canonical-root-ci-01,canonical-root-audits-01,installed-physical-01,
focused-parser-web-01 (original failure),optional-peer-literal-diagnostic-01,
focused-parser-web-02 (complete replacement) andtypecheck-01. The native
workflow now selects44modules. Its expected1922cases remain an expectation
until the full native reporter reconciles them; the application706cases are
unchanged. FDD APK/Simulator/backend/native results retain their original FDD
bindings and do not certify this combined candidate.
