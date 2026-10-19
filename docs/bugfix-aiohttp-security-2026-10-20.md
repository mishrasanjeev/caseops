# Dependency Security Release Blocker - 2026-10-20

## Actual Failure

C12 `d7aec233d57af2670f7071c7d8e69bc6f1b80431`, tree
`d276b94b0e83d3fa3c02448aaa8b5ea1a4f66463`, remains release NO-GO.
Required Security run39298948341/job118218732094 failed strict pip-audit with
locked aiohttp3.14.3. The retained first-failure handoff has SHA256
`b20c44a92f0bcd0a1842f2ddbc8f34d858ba2ad96b425195de73470892d78040`.
Do not classify this as an audit-service timeout, infer an exploit from an
installed dependency, or waive the finding using the job's severity title.

Three distinct upstream advisories identify3.14.4 as patched:

- [Resource exhaustion](https://github.com/aio-libs/aiohttp/security/advisories/GHSA-2g87-pp6c-29x5).
- [Secure-cookie plaintext leakage](https://github.com/aio-libs/aiohttp/security/advisories/GHSA-494j-54xm-rwp3).
- [Initial server request timeout](https://github.com/aio-libs/aiohttp/security/advisories/GHSA-5wr8-gcqf-gqf3).

CaseOps declares aiohttp directly; voyageai0.3.7 also imports it during module
initialization. No direct CaseOps aiohttp server or yarl runtime use was found.
The synchronous Voyage request path does not excuse the installed package.

## Narrow Remediation

Raise the aiohttp floor and lock3.14.4. Its
[upstream metadata](https://raw.githubusercontent.com/aio-libs/aiohttp/v3.14.4/pyproject.toml)
requires yarl>=1.25.1,<2, so the existing1.23.0 must become1.25.1. Only these
two package versions and the root constraint may change; preserve every other
lock identity, source, artifact and marker. Do not add a direct yarl dependency,
blanket-upgrade the lock, ignore a CVE, or alter license/security policy.
Keep application schemas, cookies, redirects, budgets and provider behavior
unchanged. Only these two package versions, the root constraint and one
standard-discovered dependency regression changed in application ownership.

## Preserved Preflight

An isolated proposal resolved exactly those two package changes. Its entire
162-registry-package lock union and138-package clean Windows default/dev
freeze each passed the unchanged strict OSV audit with zero findings, skips,
missing or duplicate identities. The local editable project is identified
separately, not silently omitted from a registry claim. All owned commands
exited naturally0 and were reaped. Preflight receipt SHA256:
`e3f728a28fb98946ba81941697b16342c05792f8f18e2405bc469d60e90683bd`.

This is proposed-input evidence. A Windows freeze differs from Linux markers
and cannot stand in for the actual hosted Security inventory. Final edited
source, frozen environment, whole-lock audit and fresh hosted Linux audit must
be reconciled separately. Preserve original findings and all raw inventories.

The cookie regression must exercise a genuinely shared Secure cookie with an
empty response URL/no domain, a non-Secure control, and HTTP -> HTTPS -> HTTP
through the cached-morsel path. A rejected localhost-IP cookie or an unrelated
domain-bound cookie is not this reproduction. Native imports and bounded
client construction/disposal must use real installed SDKs without paid or
external transport. Mocks alone cannot establish ABI/import compatibility.

## Superseded Docker06

The known Security failure was detected before canonical06 launched but its
handoff was not consumed until the parent resumed. That avoidable coordination
delay wasted a source-identical build. The permanent prelaunch rule now checks
the freshest source-bound failure handoff and required-check state before an
expensive replacement run. In-progress and already failed are different facts.

The parent preserved the build/collection/log/workspace and freshly validated
the exact native-driver ancestry, creation time and command hash before stopping
only that subtree. Canonical cleanup ran, parent91987 naturally exited1 and was
reaped. All3226 native identities were collected but zero phases executed;
all618 browsers were unstarted. These are incomplete, never successful results.
All2970 raw source files matched twice, owned resources/readers closed, and
sourcehold release seal362323205a68e7c3ed79cfa67695df39203c7745a6f0553a6882c25c81724dc3
authorized later edits. No previous native/browser result carries forward.

## Final Source-Focused Acceptance

All three complete intended modules executed: test_embeddings.py11 passed,
test_ai_money_embedding_boundary.py47 passed, and the new dependency module11
passed. Ordered collection, execution and JUnit agree:69 cases/207 successful
setup/call/teardown phases, no skips/errors, with an actual completion event.
Four real native extension imports, both real Voyage client constructors,
bounded aiohttp disposal and both shared-cookie cache orders passed with zero
network-transport attempts. The original3.14.3 six-case control retained four
native-import passes and both intended cookie failures, all18 phases; it was
not a full-old-module execution. The same regression bytes pass after the fix.

Final-source frozen sync, lock consistency and Ruff passed. Strict OSV audits
again reconciled all162 registry-lock and138 Windows-installed identities, zero
findings/skips/missing/extra/duplicate identities. All eleven stages naturally
exited0 and were reaped. No T .venv or external provider was used or mutated;
no container, network or database-server resources were created. All2972 raw
source hashes were equal during the measured interval.
The parent subsequently updated only documentation; the three tested app-input
hashes were independently rechecked unchanged. This qualification does not
turn a dirty-tree proof into an exact committed-image acceptance.

Final focused proof SHA256:
`3ead6498e6cce6b7012b70ea3a41483fa5723cea81f685b4bd1225fa6e667592`.
Independent final source review SHA256:
`766fccde94cef26d7b74018efa35d59834ff85ee0e6a5062f518e5ba9eb1c82b`.
The literal minimum-version admission assertion is a nonblocking future-update
maintenance note, not an application safety or release waiver. Actual Windows
CPython3.13.14/uv0.11.24 proof remains distinct from Linux CI/Docker uv0.11.6.
The two server-resource advisory mechanisms were not separately exploit-replayed;
their patched installed version and complete strict audit were checked.

## Remaining Acceptance

The complete current API/frontend/security and CodeQL inventories, fresh
canonical Docker07, normal canonical-main merge,
main gates, guarded exact-SHA deployment and exact-serving production Playwright
remain unaccepted. Earlier row-specific production passes keep their original
scope; Ram's historical screenshot and unknown reopening incident are still
Inconclusive. This document authorizes no production release or verdict upgrade.
