# Real Local Docker Fixture

J20/M22, US-MOB-01..04/05/06/08; supports the six-case native core gate and
MOB-01/04/07/08/09/11/14/20/30 prerequisites. Provisioning is not Android acceptance.

```powershell
python scripts/mobile/local-bootstrap.py up --mfa
python scripts/mobile/local-bootstrap.py status
python scripts/mobile/local-fixture.test.py
```

The default cache is `$HOME/.cache/caseops-mobile/local-docker-20261025`, outside
Git and restricted to the current Windows user/SYSTEM. A second invocation uses
a fresh `--cache` and unused `--api-port`/`--web-port`. Never replace a failed run.
Optional `--credentials /absolute/local.json` accepts the supplied synthetic
`email` and `password`; otherwise the fixture generates a random password.
Credentials and TOTP enrollment material stay in `credentials.json`, not logs,
fixtures, CLI arguments, source control, or native storage injection.

Default origins are API `https://10.0.2.2:8443` and web
`https://10.0.2.2:3443`. The CA is `tls/ca.crt` in that cache. The leaf SANs are
`10.0.2.2`, `127.0.0.1`, and `localhost`. Provision trust in the dedicated test
binary/browser using that public CA; never disable certificate/hostname checks
or enable release cleartext. Native build/emulator owners handle trust and app
installation. This helper never starts Metro, changes policy, installs browser
cookies, injects native tokens, accesses production, or calls a paid provider.

`compose.mobile-local.yml` builds the canonical API and production-mode web
Dockerfiles. A unique project owns its PostgreSQL/document volumes, migrated
fresh database, real ClamAV, Valkey, API, web and TLS gateway. Only the gateway
publishes loopback ports. API/web/database/scanner have no Internet-capable
network; deterministic LLM configuration and disabled case providers retain
no-paid isolation. No shared application database or template clone is used.

`source-before.json` and `source-after.json` must match for both image scopes.
Clean inputs report their actual HEAD through `/api/build`; dirty inputs report
`unavailable`, with the full content fingerprint in the source-bound revision
and receipt. The native exact-SHA gate must not be weakened to accept dirty API
builds. Parent freezes/rebuilds source before final certification.

`seed.json` identifies the exact synthetic operator, workspace, matter code/ID,
dated task/hearing, explicitly synthetic manually seeded draft version, clean scanned source, disposed
negative matter and separate-tenant negative matter. The target begins with
zero notes; the native gate owns its single note operation. Seeder HTTP calls
use real routes and the no-paid marker. It proves clean byte-identical download,
EICAR rejection, terminal-write and cross-tenant denial. `--mfa` enrolls actual
TOTP through supported endpoints; the operator browser must still sign in and
complete its own required MFA and PKCE consent. No QR/secret media is retained.

`receipt.json` provides backend/web identity, nonsensitive container/image IDs,
gateway run ID and trusted host-side `gatewayUrl`. Use those plus `seed.json`
to complete the binary/device/IDs portion of `CASEOPS_MOBILE_FIXTURE`. Host Node
processes can trust the local CA with process-scoped `NODE_EXTRA_CA_CERTS`; this
does not change the app's HTTPS enforcement. Android runtime origins use the
emulator host alias, not host loopback.

Native gateway requests need their own authoritative no-paid marker and an
exact admitted method/path. Browser handoff calls retain actual cookies/CSRF
and only allow reviewed auth endpoints from the local web origin; those calls
must send the local web build's own no-paid marker. The gateway never supplies a
missing marker. CORS preflight is forwarded, never a paid call.
Queries, bodies, cookies, passwords and tokens are absent from the fsynced
`gateway-events-*.jsonl` journals. The gateway never follows redirects or retries.

`probe` is read-only with respect to fixture records and retains a fresh log:

```powershell
python scripts/mobile/local-bootstrap.py probe
python scripts/mobile/local-bootstrap.py auth-probe
python scripts/mobile/local-bootstrap.py scanner-probe
# Only when the native owner explicitly directs shutdown:
python scripts/mobile/local-bootstrap.py stop
```

`stop` validates exact project ownership, stops only those containers and keeps
all volumes/evidence. It never prunes Docker or deletes resources. Raw build,
migration/startup, seed and probe failures remain in their original paths.

After the web transport owner closes changes, `resume --mfa` rebuilds the exact
current web snapshot with `NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=1`. It derives
an outside-Git Dockerfile from the canonical file by adding only that build
argument/environment pair. It preserves the canonical security/dependency build
steps and retains the derived file's hash. A changed API source requires an
explicit `rebuild-api`, not a false SHA update. Existing partial synthetic seeds recover only
through their real account password and unique server identities; no user or
terminal record is reset. A completed seed cannot be replayed.

`auth-probe` uses actual returned browser cookies, CSRF, MFA, PKCE and native
token endpoints in memory. It proves one note on a separate uniquely named
matter, disposes that proof matter, rotates/logs out, and asserts the native
target still has zero notes. It does not prepare the device browser, set app
tokens, or certify browser/native UI.

After all API writers close and parent freezes the candidate, run
`python scripts/mobile/local-bootstrap.py rebuild-api --mfa`, followed by
`python scripts/mobile/local-bootstrap.py resume --mfa` if the web source/release
identity changed. The API build uses the canonical Dockerfile, retains before
and after snapshots, migrates only this owned database, preserves all seeded
records/history and emits new immutable receipts. Dirty API builds honestly
report `unavailable` and cannot satisfy the native exact-SHA gate. No commit,
source freeze or final Android certification is performed by these helpers.
`current-receipt.json` is a mutable pointer to the newest immutable receipt;
earlier receipts remain unchanged.

`scanner-probe` runs the production scan function against the real networked
ClamAV with clean/EICAR files, captures the daemon version and hashes and asserts
that required scanning is configured. It is not a fabricated upload DTO or a
post-start scanner-outage proof. It does not stop/pause the scanner or mutate
fixture records.

Upload is not admitted by the six-case core route inventory. After the upload
worker's full lifecycle/race tests and the rebuilt serving API are verified,
`python scripts/mobile/local-bootstrap.py admit-upload` admits only the seeded
Matter's exact attachment POST. It refuses the old API unless its actual
OpenAPI multipart body contains `expected_lifecycle_version`, retains the
prior route inventory and keeps the fixture's 1 MiB request limit. This route
admission is not proof of the worker's locking/regression tests or a full-size
upload acceptance. No wildcard, source-download or paid PDF route is added.

## Dated 22-Case Extension

`extend --udid <dedicated-emulator>` adds supported API identifiers without
replacing existing values, a separate MFA-enrolled member, member-owned task,
fresh lifecycle/access targets and one restricted-Matter grant. The original
owner/seed/history remain unchanged. Each attempt retains its journal and each
successful iteration writes immutable `extended-seed-*.json` expectations.
The member is essential: owners bypass restricted Matter access. The locale
receipt is a read-only observation, not native rendered-label acceptance.
The QA agent alone owns further emulator/browser work.

`local-owner-controls.mjs` implements the four harness operations. It verifies
hashed binding/extension/Python evidence and the exact owned running API image,
then uses real PostgreSQL and canonical lifecycle/access services. SQL connect,
statement and lock budgets plus an absolute child deadline fit inside the
harness's ten-second bound. Mutations have exclusive no-replay attempt files;
no direct status overwrite, fabricated route, reopen or token injection exists.
`local-owner-read.mjs` only proves fresh baseline reads; it never disposes or
revokes. Bindings must be refreshed with `bind-owner` after the final API build.

`admit-source` admits only the original seeded source's canonical GET after
metadata-hash reconciliation and proves full/hash-identical and 206 Range
responses through verified TLS with actual no-paid headers. Its receipt binds
the actual serving image identity and must be replayed after the final rebuild.

After the parent supplies the frozen commit and explicitly directs rebuilds:

```powershell
python scripts/mobile/local-bootstrap.py rebuild-api --mfa
python scripts/mobile/local-bootstrap.py resume --mfa
python scripts/mobile/local-bootstrap.py bind-owner
python scripts/mobile/local-bootstrap.py admit-source
python scripts/mobile/local-bootstrap.py begin-core-ledger --mfa
```

`begin-core-ledger` refuses dirty or mismatched image scopes, preserves the
prior ledger including deliberate negative probes, and starts a new distinct
gateway run with a new immutable isolation receipt. It is never run during an
active native journey. Ordinary TLS negative controls belong to earlier
receipts, not inside the new 22-case traffic ledger. CORS preflights and public
identity reads are explicitly classified without fabricating a native marker.
All authenticated API requests still require the client-supplied marker.
One exact DELETE is admitted only from the real bounded native sessions
response's sole current non-revoked ID, then consumed once. No wildcard is used.
These tools do not reduce or mark passed any of the 22 native cases.
