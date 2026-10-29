# Scoped Node CI transport correction, 2026-10-28

The published `df4b299a` attempt is retained. Its Windows dependency job failed
in trust preparation before npm installation, installed-parser checks or audit.
The original public diagnostic did not identify the internal guard; the later
missing-artifact error is downstream, not a dependency vulnerability verdict.
Fresh Windows execution is still required. Mac controls do not certify Windows
ACLs or the Windows installed dependency graph.

The later published `75196` Windows attempt returned the fixed diagnostic
`HOST_TRUST_WINDOWS_ACL_TIMEOUT` after about 5.3 seconds, before npm or test
bodies. This establishes timeout, not which operation consumed the interval.
That original run is retained separately from the generic `df4b299a` refusal.

The replacement keeps Windows PowerShell 5.1 and the existing five-second
query/twenty-second helper bounds. It uses the Framework
[File.GetAccessControl](https://learn.microsoft.com/en-us/dotnet/api/system.io.file.getaccesscontrol?view=netframework-4.8.1)
and Directory equivalent with only `Access,Owner` sections. It reads explicit
and inherited ACEs as SIDs, with the same writer mask and owner predicate.
It uses no `Get-Acl`, module-import or JSON-formatting cmdlet. Four fixed
milestones describe script entry and completed ACL, identity and rule reads;
they contain no path, SID, account or environment data. Failure remains closed,
including missing/malformed progress. A timeout with no marker remains an
observation, not proof that the script never started. Every file has a fresh
metadata/ACL observation; no result is cached. Actual Windows performance and
ACL acceptance require a fresh hosted run.

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

The subsequent e141 Windows job completed the bounded ACL query and refused
`ownerMatches=false` in 2.965 seconds. The retained log does not identify the
object role or owner class. It does not establish a foreign-writer failure or
a normal default-owner cause. Diagnostic source now reports only fixed object
roles, owner/token-owner classes and safe/unsafe writer classifications on this
refusal. It never emits SIDs, account names, paths or raw PowerShell output.
Current-owner and writer admission remains unchanged; no existing or newly
created object's ownership or ACL is modified. A fresh Windows observation is
required before claiming a cause or an ownership remediation.

The e674 hosted job supplied the next concrete boundary:
`SOURCE_HELPER_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_WRITE_SAFE`.
The original helper was owned by Builtin Administrators while the current token
reported its user as the default owner; the DACL passed the unchanged writer
restriction. This identifies that source input only. It does not establish the
owner of a later output or explain how the checkout acquired that owner.

The Windows CI entry now treats the two exact reviewed H/B Git blobs as public
input data, before importing H. A separate bounded read admission permits this
observed Administrators-owned input class only with the same safe writer set,
full independent named/descriptor frames, namespace checks, exact size, SHA-256
and Git-blob SHA-1. It is not a runtime owner exception. Both source files must
pass before any source-copy payload is written. Unix keeps its original entry.

The entry exclusively creates a new invocation-owned directory and two files,
writes retained input bytes through their held descriptors, fsyncs, makes only
those new descriptors readonly, and verifies same-descriptor readback. Every new
object must pass the existing strict runtime owner/ACE rule; no existing object's
owner, ACL or mode is changed. Two bounded Framework observations bind all six
objects and their complete Access/Owner descriptor hashes. Source frames, copied
frames and the exact two-name namespace are reconciled before return, with
independent descriptor closure on every refusal. The retained copied H bytes are
imported as a data URI; H and B then enforce their unchanged strict admission on
the copied paths. Policies bind those new paths and require fresh preparation.
The original checkout is not imported by pathname on the Windows entry.

Source staging and CI preparation share the original thirty-second deadline.
Each Framework query retains the five-second bound, and the existing helper's
twenty-second preparation budget must remain available before it runs. Command
files and anonymous npm configuration still use their original strict owner
checks; the source diagnostic does not authorize relaxing those objects. Actual
Windows acceptance remains pending a fresh hosted run. Portable filesystem and
synthetic ACL controls establish their stated boundaries only.

A close refusal is recorded by a fixed diagnostic independent of the original
body fault. Cleanup never attaches properties to that fault, including a frozen
Error or a primitive, and never retries an uncertain close. Every other held
descriptor still receives its one close attempt. A close failure after an
otherwise successful body refuses the result and purges the retained buffer.

The subsequent `376a6cf5` hosted job refused the six-object ACL response protocol
in 2.451 seconds, before dependency installation. The complete log contains no
response shape or failing object/predicate. That boundary remains unknown. The
JavaScript-evaluated PowerShell row/emitter was separately retained and executed
with six fixed public boolean/hash rows under PowerShell7: its actual output is
valid JSON with the expected types. This is formatter evidence on that host,
not a Windows ACL observation or proof of the hosted refusal's cause.

The CI decoder now reports one fixed object role and one fixed failure class:
JSON/array/row/field/type shape, unsafe writer, missing token user or invalid hash
format. Unknown keys, values, raw PowerShell output, paths and SIDs stay private.
The same six rows, exact keys, boolean predicates, hash format and owner rules
remain mandatory. A false writer/token predicate remains refused; it is no
longer indistinguishable from malformed JSON. Source pins, query5s, helper20s
and CI30s limits remain unchanged. Fresh hosted execution must identify the
actual condition before any further ownership remediation.

The fresh `2dead9c8` Windows job identified the actual refusal:
`CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_PARENT_DIRECTORY_WRITE_UNSAFE` in
2.724 seconds. The parent directory's writer predicate was false. The public
diagnostic does not identify the foreign SID or say that the original source
files were unsafe; no broader owner/ACE permission follows from this result.

The first local repair used a path-based ACL setter after exclusive mkdir. Its
controls are retained, but source review rejected that mutation window: replacing
the pathname could change another directory before a later identity refusal.
Those controls do not certify the replacement below.

Before source staging, the Windows entry chooses an absent random final leaf
under the admitted runner temporary root. A fixed in-process Reflection.Emit
binding invokes documented CreateDirectoryW with SECURITY_ATTRIBUTES containing
the complete protected descriptor. FALSE always refuses, including an existing
leaf; it never opens an existing directory to change its ACL. No path-based ACL
setter is present. The descriptor sets the current user as owner and exactly
current-user, SYSTEM and Builtin Administrators inheritable FullControl entries.
There is no Users, AuthenticatedUsers or arbitrary default-owner exception.

After exclusive creation, a reparse-aware read-only directory handle binds its
normalized local path, volume/file identity and creation time. GetSecurityInfo
reads owner and DACL through that handle. Protection, current owner and exact
explicit rules are mandatory, with bounded descriptor/path buffers. Every handle,
unmanaged allocation and pinned buffer has an independent final cleanup attempt;
no acknowledgement is emitted if cleanup fails. The public result contains only
fixed booleans and bounded numeric identity strings. Five fixed progress markers
contain no path, SID or arbitrary exception. This uses WindowsPowerShell5.1
without module autoload, Add-Type or a compiler child.

Node compares that readback identity to the fresh canonical nonlink directory,
including the qualified Windows named-dev-zero rule, then checks its empty
namespace and full metadata. Staging still applies the unchanged strict six-object
owner/ACE checks before reading or writing source payload. Original checkout,
ancestors, command files and existing owner trees are untouched. The Unix entry
is unchanged. Each new name is attempted once; uncertain creation is never retried.

The query remains bounded to five seconds inside the existing thirty-second CI
deadline and twenty-second helper reserve. Atomic descriptor application to the
new leaf does not claim an atomic whole-namespace snapshot or lifetime process
observation. Mac filesystem controls and PowerShell7 grammar/binding controls
remain scoped evidence; actual Windows creation and inherited DACL acceptance
still require a fresh hosted run.

The later `a16a6e37` hosted attempt refused `CI_TRUST_COMMAND_OWNER` in
6.171 seconds before installation. That diagnostic conflates newly created
anonymous npm configs and the existing GITHUB_OUTPUT file, as well as subprocess,
protocol and owner/writer failures. Total preparation duration does not identify
a four-second child timeout. No specific owner class or ACE can be inferred.

The CI command-file query now retains fixed GITHUB_OUTPUT, NPM_USER_CONFIG or
NPM_GLOBAL_CONFIG roles and fixed progress/cause classifications. A negative
owner/writer result contains only bounded owner/default-owner classes and Boolean
predicates; no SID, path, account, environment value or arbitrary stderr is
reflected. Successful proof remains the original SAFE acknowledgement. The same
Framework Access/Owner read, four-second child deadline, owner predicate, writer
mask and trusted principals remain mandatory. No existing or newly created
object's ACL/owner is changed by this diagnostic. Fresh hosted Windows execution
is required to identify the next concrete condition before remediation.

The following `301a0d5e` run refused
`CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_HELPER_INPUT_WRITE_UNSAFE` before npm.
That identifies a nonexclusive writer observation on the original public helper
input; it says nothing about the protected new parent, runtime copies or command
files. The prior a16 command-file failure remains a separate unknown condition.

Only the two fixed colocated public H/B INPUTS may now carry that observation as
public-data provenance. A private producer token is available only for the exact
literal pin records/paths; the exported decoder remains strict by default.
Original owner admission and every full descriptor/named/namespace/ACL frame are
unchanged. Both held inputs must satisfy their literal SHA-256, Git-blob SHA-1
and extent before any staging payload write. Both complete input frames are
reconciled again after those byte proofs and before the first payload write.
Only the retained reviewed buffers enter new exclusive copies; neither original
pathname is imported or reopened for execution. Final input/ACL checks remain.

Parent/runtime directories, copied executables, npm config files and
GITHUB_OUTPUT keep every strict owner/writer rule. No public-input class applies
to them or to arbitrary source paths/digests. Returned provenance distinguishes
the observed nonexclusive input ACL from immutable-byte authority; it never
reports that unsafe source ACL as safe. Unix behavior and deadlines are unchanged.
Fresh Windows execution remains required, and no result rewrites the earlier
failed runs or proves the still-unobserved command-file condition.
