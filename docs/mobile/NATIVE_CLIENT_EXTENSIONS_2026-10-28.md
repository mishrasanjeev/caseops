# Native client extensions, 2026-10-28

This is a separate executable inventory: **24 cases, 72 setup/call/teardown
results and up to 24 Appium sessions for each platform**. Collection does not
execute a case. Core23, Files17 and the existing V1 inventories are unchanged.
The earlier unarmed inventory and failed native runs remain historical evidence.
No native acceptance is established by the source or mocked controls below.

The order is camera (6), local lock (5), record links (5), retained reads (4),
then minimum-version policy (4). VERSION-02/03 prove the same current native
session across a moving floor and rollback. VERSION-04 independently exercises
unavailability/retry, an additional floor, actual sign-out below that floor,
active-session-list absence, a final rollback and signed-out UI. An enabled
button alone is not the logout assertion. No mutation or failed/unknown command
is automatically retried.

## Public collection and preparation

Use the accepted Node executable, Python 3.13 and explicit Xcode
`DEVELOPER_DIR` for iOS. Collect both platforms separately:

```sh
node scripts/mobile/run-client-extensions.mjs ios --collect
node scripts/mobile/run-client-extensions.mjs android --collect
node scripts/mobile/prepare-client-extensions.mjs --pending ios
node scripts/mobile/prepare-client-extensions.mjs --pending android
```

The collections contain every callback's source digest and all 72 phase
identities. Pending templates intentionally contain no live artifact, device,
credentials or backend evidence. Create new immutable completed requests;
never edit a retained template or reuse an old device/member observation.

Before either member reader, the runner validates the exact clean app source
and separate harness fingerprint, actual APK or signed Simulator bundle hash,
artifact version observation, installed identity/current Android boot and
16 KiB page size, current API **and** web revisions, the actual gateway epoch
and enabled hash-pinned profile, current device/selector/OS-recipe bindings,
accepted executable identities, and complete Appium/Webdriver runtime trees.
The Appium process must be the current owned UID/PID/UTC command identity and
own the observed loopback listener at the requested port. Android/iOS artifact,
source, backend and Appium proofs are independent. No spoofed version header,
mock biometric or platform-named JavaScript export is native evidence.

The camera observer reads only the app-owned ImagePicker SDK directory after
capture, or at cleanup. It never reads/rewarms provider/OSInbox originals.
Camera counts do not include the separate legacy Files fixture counts. Capture
bytes and hashes are retained; no metadata-stripping claim is made. The fixed
positive upload bound is 900,000 bytes under the existing bounded gateway;
larger captures are cleared and remain unverified for that positive journey.

## Fixture authority and exact commands

The new profile is disabled by default. Only the exact profile name
`native-client-extensions-v1` selects its separately hash-pinned module. It
cannot accept arbitrary owner recipes, SQL, token injection or arbitrary native
mutations. Its owner uses normal login/MFA and finite normal HTTP calls. Its
one explicit access-wall test acts only on the registered synthetic Matter and
restores the exact acknowledged wall once. Unknown wall outcomes stop the run.

A separate normal producer in `local-client-extension-fixture.py` creates three
synthetic Matters, two mock-generated recommendations and a recorded decision,
three hearings, two generated packs and one review through the actual APIs.
Each of the **12 POST acknowledgements** is retained before continuing. The
normal producer has no DB import path. Use the exact completed request digest
and the canonical source-bound Compose command/environment:

```text
<canonical compose argv> exec -T
  -e CASEOPS_NATIVE_CLIENT_DATASET_GO=EXPLICIT_OWNED_SYNTHETIC_PRODUCER
  api python /mobile-fixture/local-client-extension-fixture.py
  /fixture-state/<new-normal-request.json> <sha256>
```

The actual local API `K_REVISION` must match the admitted backend revision;
cloud service identities and non-mock providers are refused. Both serving
revisions are read before the protected owner file. The current actor, company
ID and synthetic company slug must match after normal authentication.

Only the **separate** retained-row request grants DB writer authority. It writes
exactly two predeclared Recommendation IDs (oversize text and invalid legacy
JSON), under the admitted local PostgreSQL/process/tenant/member/Matter and
observed lifecycle locks. A real normal-generated sibling/model run is
required. Existing source/outbox snapshots must stay equal. The commit receipt
is durable before normal API detail/page readbacks; a readback failure cannot
cause another insert. Its distinct command uses:

```text
<canonical compose argv> exec -T
  -e CASEOPS_NATIVE_CLIENT_RETAINED_FIXTURE_GO=EXPLICIT_OWNED_SYNTHETIC_PRODUCER
  api python /mobile-fixture/local-client-extension-fixture.py
  /fixture-state/<new-retained-request.json> <sha256>
```

Do not execute either producer without the separately admitted owned local
backend/DB resource window. Native read consumers gain no DB authority.

Host paths and `/fixture-state` paths are different namespaces. Registration
composition requires actual public cache-mount/effective-UID metadata, with
separate same-byte host/runtime credential references. It does not assume that
host and container UIDs match. A new public registration/descriptor is emitted
with exclusive writes by:

```text
node scripts/mobile/prepare-client-extensions.mjs --register <request> <sha256>
node scripts/mobile/prepare-client-extensions.mjs --compose <request> <sha256>
```

The fixture composer consumes actual normal/retained readbacks and observed
native selector/OS recipes. Recipes use only observed enabled controls, one raw
protocol click per action, and bounded waits. There are no guessed coordinates,
provider URI opens, `pm grant`, TLS bypasses or automatic uploads. Scoped Fact
locators bind the exact record/label, so another generic “Not recorded” label
cannot satisfy a nullable-value assertion.

## Immutable policy transitions

The four owner phases are `floor`, `rollback`, `exit-floor`, `final-rollback`.
Each has a **new immutable config/override/registration/receipt/epoch**. Existing
config, gateway journals, private metadata, PostgreSQL data mounts and original
receipts stay retained. The Native/Appium runner has no Docker authority.

`prepare-client-extensions.mjs --policy-plan <request> <sha256>` emits the exact
new config and override and the bounded invocation plan. A separately admitted
canonical local operator obtains the actual command/environment from
`local-bootstrap.compose(cache, new_configuration)`, appends `-f <new override>`
to those Compose options, then invokes the plan's exact suffix:

```text
up -d --no-build --no-deps --force-recreate --wait --wait-timeout 60 api gateway
```

The command bound is 90 seconds, with no retry. It does not rebuild images,
restart PostgreSQL, replay migrate or recreate web/scanner/valkey. The operator
must first prove fresh actual Docker filesystem capacity of 64 GiB and 100,000
inodes, plus source/image/owned-project and protected-identity admission. This
plan is not a replacement for those guards. It performs no transition itself.
Do not claim that a plan or Compose template is an executed configuration.

After the actual transition, retain the new seven-role container/config/TLS/
API/web/epoch observation and the old gateway ledger. The independently
executable ACK consumer:

```text
node scripts/mobile/client-policy-checkpoint.mjs <request> <sha256> <result-path>
```

requires exact current API, web, compatibility and gateway GET readbacks. It
binds the prior native-session observation and retained old ledger. Only that
validated ACK releases the waiting native case. Typed PG-mount/private-metadata
identity preservation is not a claim of byte-equal whole databases. The case
also reads the current actual server session before the floor/rollback claims.
The operator's attempt/unknown result must be reconciled, never replayed.

Operator completion owns a distinct finite 180-second/13-read contract; it does
not borrow or extend the 20-second interactive wait. The case still has its
300-second budget. If both extra final transitions cannot fit, the case stays
failed/unverified; no timeout waiver or hidden suite filtering is permitted.

## Live runner and cleanup

Only after actual fresh bindings and explicit resource admission:

```text
CASEOPS_NATIVE_CLIENT_EXTENSIONS_GO=EXPLICIT_OWNED_NATIVE_WINDOW
node scripts/mobile/run-client-extensions.mjs <ios|android> --request <request> <sha256>
```

The request must admit the full inventory and at least its complete fixed
60-minute serial budget plus 120 seconds of resource cleanup reserve. The
report/claim directory is a fresh owned private directory outside the repo.
Claims are exclusive and never reset. Each case creates/deletes only its own
Appium session; it does not install, boot, clear app data, stop an unowned
server, mutate provider originals or perform cloud/provider I/O. Known external
unavailability stays explicitly unverified; an unknown native/owner outcome
blocks further setups while preserving all 72 phase results and cleanup errors.
The outer owned VM/Appium keeper remains separately responsible for exact
PID/parent/UTC/argv shutdown and listener/process absence.

Simulator/emulator camera, prompt, foreground and protected-marker workflows
remain scoped to that OS/artifact. Real sensor, enrollment, camera metadata and
physical privacy/accessibility acceptance remain separate. Verified HTTPS links
require an actual production-domain association and signed artifact observation;
a local custom URI or a fixture Boolean cannot establish it. The summary never
promotes these source controls to physical hardware acceptance.

## Bounded runtime receipt transport

Prepare each public filesystem inventory with `prepare-client-extensions.mjs
--runtime-inventory <request> <sha256>`. The prepared request names the platform,
`webdriver` or `appium` purpose, canonical runtime root, exclusive public output
and an exclusive audit-manifest output outside both runtime and source. Appium
also names its normalized canonical regular entry file, which must be a file
member of that complete actual capture. Parent traversal, symlink entries and
uncaptured targets are refused before server commands. Root and audit-reference
paths must also be normalized. This preparation acknowledges no native action.

The purpose-specific inventory is version 2. Its `tree` is a strict version 3
commitment to the complete version 2, two-observation capture: canonical root,
logical and charged counts, and exact canonical JSON-with-LF manifest digest and
extent. Both native consumers freshly recapture the selected actual runtime and
compare the complete commitment before server commands or protected readers.
Legacy inline trees, one-observation receipts and hash-only objects are refused.
A receipt hash is not independent runtime observation.

Public input and projection output remain limited to 1 MiB. The separately
retained full manifest is audit-only, with an exclusive 16 MiB output bound and
POSIX mode 0600 where supported; actual Windows ACL acceptance remains separate.
It is never read as a native admission input. Capture, canonical encoding and
manifest output share the existing 5-second deadline, 50,000 charged entries and
512 MiB charged payload budget. Both complete observations are charged.

The public CLI and native runner await
the asynchronous capture, which has at most four 64 KiB buffers and four owned
descriptors, including directory inspection. The two inventories remain serial.
The serial traversal reserves one of the same four operation/descriptor slots
before asynchronous descriptor opening. Every successful callback transfers its
lease into an owned `finally`, even if the timer or another read has already
failed. Pending opens are never raced or abandoned. Malformed acknowledgements
and ambiguous constructor/close errors require isolated process exit; a
caller-owned descriptor is never inferred from its numeric value or retried.
Native canonical lookups within the four held file jobs use the callback API;
each job has at most one pending canonical or read operation. The independent
full descriptor and named frames are rebound before the first byte after that
new callback boundary. The complete final path pass has a separate four-worker
canonical phase after every file job drains; the unique directory pass still
runs child-first and root-last, followed by the external namespace fence. Any
failure waits for every dispatched callback, including canonical callbacks,
before returning. No cached canonical result replaces a fresh observation.
The live-parent identity fence uses public numeric Stats only when all five
immutable admitted BigInt identity values have exact safe-number equivalents.
An unsafe baseline selects the original BigInt reader before observation; an
unsafe or malformed observed Number refuses without a fallback retry. Every
parent is still freshly read. All independent full nine-field frames, final
reconciliation, native canonical resolution and payload reads remain unchanged.
Each leaf keeps its opened descriptor, independent full descriptor/path frames,
native canonical resolution and live parent checks through its read. A shared
byte ledger reserves read capacity and permits only one aggregate overflow byte.
On failure no new work is scheduled and every pending read finishes. Every
other definitely held descriptor is closed before refusal returns. A close error
is ambiguous:
the same number can already refer to a caller's newly opened descriptor for the
same file. It is never retried or treated as an ownership proof. The error marks
cleanup uncertain and requires the isolated caller process to exit, with its
owner proving process/group absence before reuse. Commands and protected readers
wait for successful recapture. Synchronous capture APIs remain available with
their original behavior. Source tests do not establish five-second performance
on an installed SDK or native acceptance.

The canonical codec retains each checked primitive through use. Its nine
numeric metadata fields form one at-most-512-byte chunk per row with unchanged
field order and encoding; directory names still stream under the same output
bound. Required-entry projection computes its constant relative key once before
searching the private captured rows. Codec-only saved-manifest measurements do
not certify a fresh SDK inventory or its shared capture deadline.

Failed or partial outputs remain retained and produce no success reference. A saved
large manifest can establish codec/transport compatibility only, not current
SDK, server, device or native acceptance.

The asynchronous capture retains a frozen child-to-root chain of admitted
primitive parent paths and identity baselines per inventory. Every original
parent lstat remains live and ordered; no filesystem observation is cached.
Fast comparisons preserve strict Object.is identity, including signed zero,
first-field unsafe rejection and one read of each observed identity value.
Constructor-count, getter-order and actual grandparent replacement controls
cover this implementation separately from timed SDK capture acceptance.
