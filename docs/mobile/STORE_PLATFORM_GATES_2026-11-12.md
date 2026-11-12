# Independent platform store gates — 2026-11-12

J20/M22 / US-MOB-01..08: **Partially implemented**, distribution verification
**Inconclusive**, release **NO-GO**. No AAB or IPA is certified by this document.

The user requested Google Play first while iOS continues independently. The
packaging executor previously required both nativeAndroid and nativeIos before
either platform could start. Its reviewed manifest now explicitly binds its
platform with schema version 2 and requires the exact 15-gate inventory: all
14 shared gates and the complete native gate for the platform being packaged.
The opposite platform is not claimed as passed. Old combined manifests, a
foreign native gate and mismatched platforms are refused before signing reads.

The shared mobile, web, common API, PostgreSQL, secret/history, CodeQL analysis,
CodeQL alert verdict, whole-lock and installed advisories, licenses, SDK, Linux
image, required CI and privacy policy gates are unchanged. Signing identities,
build-number reservations, source fingerprints, private input ownership,
monotonic store history, command deadlines, artifact inspection and postflight
checks remain. Own-platform native acceptance remains mandatory.

The complete packaging execution module passed 32 contract cases, including
every individual common/native gate failing before any signing or build
command, both platform command graphs, all private/signing/source/cleanup
boundaries and wrong-platform/old-schema refusal. Its artifacts are synthetic;
it cannot establish a distribution signature, native pass or upload. Proof is
retained outside Git in the task cache as `store-platform-gates-unit-01.log`.

Production HTTPS LINK-05 still needs an actual signed candidate. The current
own-platform native-before-build rule makes that qualification boundary a
separate unresolved dependency; this patch does not waive it or fabricate a
native pass. A separately marked non-submittable qualification artifact and
an artifact-bound final promotion check are still needed before solving that
cycle. The 83-case platform suite, full current source/CI verification, actual
signed build and Play submission remain outstanding.
