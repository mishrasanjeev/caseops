# Scoped host Node trust and native tooling (2026-10-28)

This is host preparation, not native application or store acceptance. The old
Appium 3.8.0 and driver homes remain retained failed dependency scopes. Earlier
package-advisory responses remain useful package evidence; they were fetched
before the host Node trust remediation and do not establish clean TLS defaults.

The current source pins Node 24.15.0/npm 11.12.1, Appium 3.9.0, WebdriverIO
10.1.0, XCUITest 12.22.2 and UiAutomator2 8.7.3. Use official releases, without
an override or modified package version. Old XCUITest 12.20.0 and UiAutomator2
8.7.0 bundle vulnerable exact dependencies; resolving the core alone cannot
certify those driver homes. Every actual nested installed identity and hidden
home-lock node must be inventoried. Absent optional packages are explicit
omissions, including platform-matching optional binaries, rather than silently
accepted platform exclusions. A newly generated root lock is a different graph
and cannot certify the Appium CLI's existing physical home.

## Node policy

`scripts/mobile/host-node-trust.mjs` accepts only the complete reviewed bundled
DER set for Node 24.15.0 (145), or Node 22.14.0 (149), and their exact
already-clean equivalents. It removes only emSign ECC Root CA G3, SHA256
`86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b`.
Every other DER is retained. Missing, duplicated, substituted and unknown roots
refuse. The resulting base stores contain 144 and 148 certificates respectively.

`prepareHostNodeTrust` writes a new exclusive private directory, owner-only
0600 PEM and policy, and an owned empty CA directory. The public descriptor has
kind `caseops-host-node-trust-v1` and binds the exact helper/bootstrap bytes,
Node version, complete sets, bundle, role and optional one public fixture CA.
Its authority pair is `CASEOPS_HOST_NODE_TRUST_POLICY_FILE` and
`CASEOPS_HOST_NODE_TRUST_POLICY_SHA256`. It returns a child environment; it does
not change the shell, operating-system store, or current Node TLS defaults.

A trusted outer launcher must read/hash the reviewed helper through its held
FD and execute that retained buffer. It supplies `sourceRefs` to preparation.
The inherited bootstrap is likewise a bounded data URI built from its held
reviewed bytes, avoiding a later helper-path module reopen or Windows spaces.
The Windows provisioner's real outer bootstrap is exercised as Node source by
its colocated tests. Ordinary debug CLI preparation is not an independently
verified producer binding by itself; native release launchers must bind the
actual reviewed source and policy references before private admission.

The exact scoped `NODE_OPTIONS` is `--use-openssl-ca` plus that one derived
bootstrap URI. `SSL_CERT_FILE` selects the bound base PEM and `SSL_CERT_DIR`
selects the bound empty directory. Unknown/system/OpenSSL overrides, TLS bypass,
additional preload flags and npm CA/verification bypasses refuse. The Node test
runner may repeat only the exact approved OpenSSL flag/bootstrap URI and its
compiled default cipher list; changed values still refuse. Node 24's
OpenSSL-mode default getter actually reports zero before activation. The
bootstrap replaces the current thread's defaults from the verified held PEM
before the real npm/Appium/entry import, then requires the exact 144-root getter
set. Node 22 lacks both APIs: it verifies the selected bundle and must use actual
default HTTPS and fetch transport evidence; it claims no default enumeration.

Only explicit `native-qa` may admit one exact descriptor-bound self-signed
fixture CA through `NODE_EXTRA_CA_CERTS`. Base role never accepts it. The QA
policy does not authorise credentials, paid providers, arbitrary destinations or
production use. Normal Worker/subprocess inheritance is tested. An explicit
worker/child env, execArgv or custom TLS `ca` override is outside that proof and
needs its own admission. No universal thread/lifetime/default-agent claim is made.

All loopback verification constructors send
`X-CaseOps-Automated-Test: no-paid-providers`; the server checks the exact value.
Repository fixtures exercise real default HTTPS and fetch: trusted synthetic CA,
unknown CA, and wrong hostname. They do not disable certificate or hostname
verification. Separate synthetic file-only/empty-file controls establish actual
OpenSSL selection without QA EXTRA, and are labelled transport-only. No live
key or enrollment is read. Node 22's selected148 store must not be silently used
as the Python/Ruby127 or Java117 store: cross-runtime children require explicit
neutral rebinding to their independently validated recipe.

## Provisioning and readiness

Run the Windows PowerShell 7 provisioner from a verified checkout. It performs
held-source preparation and actual scoped verification before even npm --version,
then uses anonymous private npm configuration and a fresh per-platform common
root `{core,home}`. No old cache is overwritten. Its 900-second setup contract
clips each public tool child to 300 seconds with cleanup reserve, preserves real
exit codes and bounded stdout/stderr (successful stderr is valid diagnostic
output). Interrupted roots are unknown, retained and never replayed. It signals
only the exact owned root process; it does not claim complete Windows descendant
absence. Actual Windows provisioning and its stronger release process/resource
acceptance remain unrun. `-WithJdk` refuses an unproved .NET download; a separately
verified platform JDK is required. There is no global environment mutation.

The manual macOS npm/Appium commands in older runbooks are graph descriptions,
not permission to bypass this preflight. Launch every actual Node child with the
verified recipe derived by the held outer launcher, never by blindly copying a
logged NODE_OPTIONS value. Require fresh advisory/notice/physical graph evidence
and loopback driver health after arranging each new root.

Use a separate complete common root for each OS. Core plus selected home must
fit the unchanged native capture: two root-present complete inventories,
50,000 charged entries, 512 MiB charged payload and 5 seconds, with final every
path/namespace reconciliation. Driver-to-Appium aliases must resolve inside the
same captured root. Do not capture only core, silently skip a home, follow an
external alias, raise caps or retry a warmed failure for green. Metadata size
estimates do not prove the payload deadline. All-three union exceeds the entry
bound. New path/alias/registration arrangements need new graph/audit/notice
receipts; older hashes are not restamped.

Before native use: fresh complete locked/physical advisory zero; all exact
nested body-parser/shell-quote copies and official provenance/notices; actual
Appium/driver CLI registration; owned loopback health with zero sessions;
current trust policy; full runtime payload capture; and actual source/binary,
backend, device and provider/auth bindings. None is supplied by this document.
# Exact public checksum review after the hosted scan

The hosted tree scan of `df4b299a660e9ab00655054f7f4caf1b28a1f340`
reported the public certifi bundle checksum at line81 of
`scripts/mobile/host-platform-trust.py`. Its35 native findings and34 previously
accepted origins remain retained. The history boundary was not reached.

An independent marked HTTPS read of the official
[certifi2026.10.19 PyPI metadata](https://pypi.org/pypi/certifi/2026.10.19/json)
and its exact `certifi-2026.10.19-py3-none-any.whl` verifies these public inputs:

- Wheel:136,464 bytes, SHA256
  `42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b`.
- The wheel's `certifi/cacert.pem` exactly matches the installed120-anchor bundle:
  `50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785`.
- The complete reviewed source line has SHA256
  `0c3ed116e3a6d25ea71ba6336dabfa79c49fcdea1bc629a17ec6ce0b09637fe4`.

The HTTPS verifier used only the descriptor-held120-anchor bundle, hostname
and certificate verification, no redirects or retries, and the exact no-paid
marker on both requests. No trust store changed. The policy adds only the two
independently verified immutable local/published origin fingerprints. A
repository regression checks the current exact span and ancestral blame;
changed spans, later origins and unrelated findings remain blocking. This
review is not a successful replacement tree/history scan or a release waiver.

The first replacement's complete74 canaries and current-tree scan passed,
but its82-commit local history scan found an earlier representation of the same
official bundle digest. That separate failed history evidence is retained.
The exact additional origin is `2fe2d37cc8623fe91d9e463244a2880469939612`,
line35, with complete-line SHA256
`99aa023b175ad129caccb5840eb31efb84788a510b30f615901ed50c8a371b8c`.
Its immutable source contains the independently verified public bundle hash.
Only this separately reviewed historical fingerprint is added; the successful
tree result does not substitute for a complete replacement history scan.

