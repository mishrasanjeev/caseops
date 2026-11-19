# Windows native TLS fixture - November 19, 2026

## Scope and verdict

**Partially fixed; release NO-GO.** J14/M14 security/release acceptance.
This changes only the offline native test fixture and its retained diagnostics.
Production certificate verification, hostname verification, trust policy and
all existing five/eight/fifteen-second limits remain unchanged.

## Failed source-bound CI

PR627 head77ed25db85f91dff2b8959abf3d6beb4de496b0f, CI44573536157,
Windows job135734893585:3247 passed and one failed in316 files.
The actual fetch/HTTPS test failed during certificate preparation, before its
trusted/untrusted/wrong-host client controls. Its first OpenSSL req child was
terminated after5051ms; the concurrently started second child completed4911ms.
The later third child completed73ms. The five-second bound was enforced.
This is not evidence that a TLS denial or real client assertion failed.

The old Windows default selects Git usr/bin/openssl.exe, which imports the MSYS
compatibility runtime. Git also supplies mingw64/bin/openssl.exe: a native Windows
executable. Independently inspected PE imports and native version output show
both local executables use OpenSSL3.5.6; only the first imports msys-2.0.dll.
A local comparison did not reproduce the CI timeout, so it does not establish
the specific cause of the remote startup stall.

## Repair and focused evidence

Select Git's native Windows OpenSSL by default and verify its actual native
platform output before certificate generation. Retain native executable,
operation, budget, timeout and version diagnostics without keys or certificates.
An explicit MSYS override is rejected; a missing, failed or unsupported executable
cannot become a successful TLS check. Linux keeps its existing openssl selection.

The controlled MSYS override reached the real executable and was rejected by
the platform assertion. The complete native trust file then passed all21 cases,
including actual default fetch and HTTPS success, untrusted certificate and
wrong-host rejection, exact no-paid markers, trust filtering, startup refusal
and descriptor closure. All original case identities are retained.

External evidence: pr627-77ed-windows-job135734893585-connector.log,
pr627-77ed-windows-native-trust.json,
pr627-openssl-native-comparison01.json and
pr627-native-openssl-focused02-receipt.json under the retained merge161001 folder.
The first negative-control verifier incorrectly required a full value that the
native assertion message truncated; its failed receipt is preserved and its
unexecuted positive phase is not counted. The replacement retains and checks the
actual executable's complete metadata independently.

## Remaining acceptance

Complete replacement frontend compilation/coverage, current-head required CI,
fresh canonical Docker acceptance, exact-serving production QA and the guarded
post-QA projection resume remain required. Earlier3248-pass frontend evidence
belongs to its earlier source. No unchanged CI retry, security waiver, test
deadline increase or product behavior change is authorized by this repair.
