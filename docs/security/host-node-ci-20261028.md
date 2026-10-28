# Scoped Node CI transport correction, 2026-10-28

The published `df4b299a` attempt is retained. Its Windows dependency job failed
in trust preparation before npm installation, installed-parser checks or audit.
The original public diagnostic did not identify the internal guard; the later
missing-artifact error is downstream, not a dependency vulnerability verdict.
Fresh Windows execution is still required. Mac controls do not certify Windows
ACLs or the Windows installed dependency graph.

The existing Windows owner check only accepted `WindowsIdentity.User`.
[Microsoft documents `WindowsIdentity.Owner`](https://learn.microsoft.com/en-us/dotnet/api/system.security.principal.windowsidentity.owner)
as the token's default owner SID for newly created objects; it can identify a
user or group. The read-only query permits the actual current user, or the
OS-reported default token owner only when it is SYSTEM or Builtin Administrators.
Those are already trusted writers; arbitrary default-owner groups remain refused
because ownership itself can imply permission to rewrite the DACL.
The existing foreign-writer restriction remains independent and unchanged.
Timeout, malformed proof, owner mismatch and foreign-writer failure stay closed.
Only fixed reviewed failure labels reach the CI diagnostic; account/SID values,
policy bytes and arbitrary exception text are not reflected. This is a concrete
portable contract correction, not a claim that the original generic Windows
failure's exact cause has been observed.

The same attempt compiled the web application and TypeScript, then failed when
Next 16.4.2 started page-data workers. Its installed Worker formats inherited
Node options and the default `enablePrerenderSourceMaps: true` appends exactly
`--enable-source-maps`. A real Next Worker/loopback control reproduced the old
`HOST_TRUST_BOOTSTRAP_SOURCE_REQUIRED` refusal before any HTTPS request.

The trust helper accepts its original exact options, or those exact options
with that one trailing flag. The approved held bootstrap data URI, certificate
bundle, empty directory, role and descriptor hashes remain mandatory. Duplicate,
reordered or additional preloads/trust flags and proxy overrides are rejected;
there is no general extra-flags allowance. A repository fixture uses the actual
pinned Next Worker with one worker and no retries. Trusted, untrusted and wrong
hostname HTTPS/fetch checks retain default verification and the canonical
`no-paid-providers` marker. No inline first-party web TLS fixture is introduced.

No root set, permission, native minimum deployment target or interactive timeout
is relaxed. The five CI outputs plus four anonymous npm configuration outputs
remain per-step; no job/global trust environment is added. Updated helper and
bootstrap digests in `tooling.json` require freshly prepared policies after
integration. Old policy artifacts and failed attempts keep their original scope.
