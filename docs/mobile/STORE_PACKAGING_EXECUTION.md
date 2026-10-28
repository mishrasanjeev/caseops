# Guarded local store packaging

This adds an explicitly armed local executor alongside the unchanged plan-only
`prepare-store-packaging.mjs` recipe. With no arguments,
`run-store-packaging.mjs` returns preparation-only metadata. `--pending ios` or
`--pending android` emits a request with `readyForLocalBuild:false` and null live
references. Actual execution requires `--execute <absolute-request> <sha256>` and
`CASEOPS_LOCAL_STORE_BUILD_GO=EXPLICIT_REVIEWED_LOCAL_STORE_BUILD` on the admitted
macOS/Node24.15.0 host. Nothing uploads, enrolls an account or purchases a service.

## Inputs and authority

The outer request is exactly the schema emitted by `pendingStoreExecution`.
Its `recipe` references the original immutable plan request; that schema and
plan-only CLI remain unchanged. Other references bind the exact source tree,
reviewed gate bundle, tool inventory, actual store-history observation, approved
privacy descriptor, reservation directory and a new private output directory.
An Android request additionally references a private password JSON object;
iOS forbids it. Architectures are explicit, with Android arm64 required.

The gate bundle binds source commit/tree, mobile fingerprint/count, tools digest,
link/build/policy descriptors, signing public inputs, architecture and canonical
reservation directory. Its complete literal gate inventory must pass, including
both CodeQL analysis and alert verdict, whole-lock and installed advisory scans,
Linux image, native Android/iOS and policy approval. Gate and history observations
must be at most24 hours old. These are operator-reviewed receipts consumed by
this runner, not independently rerun gates or authenticated store-console reads.
Receipt provenance and external owner approval remain review prerequisites.

All declared tool paths, versions, owners, extents and hashes are checked. The
runtime-input list is an **operator-reviewed declared subset**; this runner does
not prove a complete installed import closure. Generated Podfile or Gradle
wrapper inputs must match their declared hashes after public prebuild and before
the signing boundary. The actual JDK/SDK/Xcode locations are tied to those inputs.
A future execution needs a fresh source-owned dependency/tool environment and
complete independently reviewed installed/runtime closure evidence.

The complete Git-tracked file bytes are checked against Git blobs, with clean
HEAD/index/untracked checks before and after execution. Both observations share
20,000 charged entries and1GiB, each clipped to120 seconds and the invocation
clock. This is tracked-file content plus root/file metadata reconciliation;
it is **not** a complete filesystem directory inventory. Ignored generated native
projects are admitted only when absent initially. Generic mobile fingerprints
alone do not cover every raw vendor distribution file: the complete Git witness,
reviewed tar/provenance and installed-tool witnesses remain necessary.

## Private boundary and one attempt

One invocation clock starts before the first request read. The whole operation
has3600 seconds, including its30-second cleanup reserve; checked FD reads and
admissions check that same clock. At most48 commands are dispatched. Command
budgets stay at their existing recipe values and are clipped to remaining time.
Build streams are bounded at16MiB each plus an overflow detector; bounded
inspection streams use1MiB each, with256MiB aggregate command output.

Actual current store maxima must be below both proposed build numbers. The
existing exclusive reservation primitive reserves both platform numbers as one
source/build/link batch. A complete matching batch can be reused for the other
platform; each platform has its own exclusive execution claim. Partial batches,
existing claims and existing output directories refuse rather than reset or
replay. Outputs use owner-private directories and exclusive0600 files.

Public viewer/prebuild/Pod preparation runs before profile/keychain or Android
keystore/password admission. iOS checks the exact installed distribution profile,
Team and application prefix separately, app identity, expiration, certificate
membership and valid private-key identity. Android copies the admitted private
keystore into owned output, obtains passwords from a0400/0600 JSON descriptor,
and verifies its private-key entry and upload certificate. Password values travel
only in child environment, never argv or persistent logs. Upload and Play
app-signing certificates retain separate roles. No key/profile is generated,
installed, exported or searched for by this runner.

The reviewed process-owner helper is retained byte-exact with SHA256
`eaa036bea90b08ba721deb4ece7286bd93315e8d64d128b646d27b78fa2176cf`.
Its bound is33 outer convergence inventories, with additional ancestry checks
inside the unchanged caller/30-second cleanup deadline. It is not a claim of33
total backend snapshots. A separate scanner experiment has reproduced its
convergence refusal during rapid Git-child churn; actual store compiler/process
acceptance is unrun and this runner does not waive that refusal. Unknown outcomes
retain consumed claims, refuse success and are never automatically replayed.

## Artifact postflight

The retained descriptor-read IPA/AAB ZIP is checked for bounded entry/expanded
sizes, CRC/extents, duplicate/unsafe names, links, encryption and unsupported
ZIP64/multi-disk forms. The limits are512MiB compressed,30,000 entries,1GiB
expanded and128MiB per member. Archive input growth and namespace replacement
refuse, with descriptor closure. An exact source/link/build/policy/notices
attestation is embedded before signing and compared from the resulting artifact.
This proves those embedded bytes, not reproducible compilation of every binary.

IPA inspection checks actual device platform/architectures, app version/build,
identifier, minimum OS, strict signature, certificate, embedded App Store profile,
Team/prefix, entitlements, associated domains and privacy metadata. AAB inspection
uses admitted bundletool/strict jarsigner plus a bounded Java JarFile verifier
that consumes every non-signature entry and requires the expected single signer.
It checks package/version/build, target SDK, release manifest flags, exact privacy
metadata, native ABI coverage and actual ELF load alignment. The archive inventory
is retained; this is not an aggregate supplier privacy-manifest or legal-policy
approval report. Postflight does not constitute App Store/Play acceptance.

## Diagnostics and present proof

Each dispatch is journaled before effect. Original numeric tool/worker status,
timeout, stream bytecounts/digests and cleanup are retained, including nonzero
outcomes and successful stderr. Potentially sensitive raw tool text is
intentionally omitted. Fixed failure classes therefore have limited diagnostic
scope; they are not complete native-tool logs or an assertion of signing success.
Original failure, cleanup and persistence failures remain separate. Unreached
phases remain unverified, and failed cleanup cannot produce acceptance.

The38 Node and14 Python controls use real temporary files, ZIP/ELF/certificate
parsers and explicitly synthetic command observations. Test adapters are code-only
and always produce `contractOnly:true`, never distribution-signing acceptance.
An actual accepted Temurin21.0.12.1+1 unsigned synthetic JAR reached the verifier
and refused with exit37; a separate actual `java -version` returned0 with retained
stderr. The earlier pipe-based source transport failed before verifier entry
(`Illegal seek`) and remains retained; the corrected transport uses the same
verified seekable anonymous FD. None is a signed IPA/AAB positive or app build.

The baseline branch is `cfcb98d7`. Its missing privacy reader intentionally blocks
real execution. The separate Host privacy implementation at `b1e0efa7` supplies
`readPrivacyPolicySettings` and the agreed compiled metadata keys after merge;
its digest binds descriptor bytes, not deployed policy content or approval.
Final integration must reconcile literal CI/LF inventories and rerun the complete
affected original recipe plus both new Node modules and Python module. Real
registered IDs, current store history, profiles/private keys, approved policy
content/URL, final security/native gates and signed-artifact positives remain
external or unrun prerequisites. No owner account, credential or tax identifier
is stored in this source preparation.
