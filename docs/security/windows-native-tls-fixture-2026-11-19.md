# Windows native TLS preparation - November 19, 2026

## Scope and verdict

**Partially fixed; release NO-GO.** J14/M14 security/release acceptance.
Use the already pinned Node22.23.4 runtime for synthetic certificate creation.
Production trust policy, certificate/hostname verification and original5s/8s/15s
limits remain unchanged. This fixture adds no dependency or network access.

## Failed source-bound runs retained

PR627 head77ed, CI44573536157, Windows job135734893585:3247 passed and
one failed in316 files. Certificate preparation terminated an OpenSSL req after
5051ms; its concurrent sibling completed4911ms and a later child73ms. Actual
fetch/HTTPS trust controls were unreached. The executable used MSYS. The local
comparison did not reproduce the remote stall, so its exact cause is unproven.

The next head578bf98b85a36b6f17b961096110c22e31f97335 selected a native
Git OpenSSL path present on this workstation. CI44581025037 job135761460466
again retained3247 passes and one failure: that executable is absent on the
actual Windows2025/VS2026 runner. This was a provisioning assumption introduced
by the repair. Preserve both failed runs; neither is a final Windows pass.

## Current repair

A repository-owned, offline Node fixture creates three fresh P-256/SHA-256
certificates for fixed local identities: trusted loopback, untrusted loopback
and a wrong-host leaf signed by the trusted root. It admits only a canonical,
empty tls directory inside its allocated temporary test root. It creates six
new files exclusively and never overwrites retained data or accepts supplied
subjects, issuer keys or certificates. Test cleanup removes synthetic media.

Certificate fields follow RFC5280; Node's native crypto performs signing.
The parent independently parses all files, checks private/public key binding,
issuer/signature, CA roles, curve and SANs, then runs the original real default
fetch/HTTPS success and certificate/hostname refusals. Trusted requests must
each carry the exact no-paid marker; rejected TLS must reach no HTTP handler.
The whole producer child retains the original5s preparation limit.

All21 original native trust cases plus one new unsupported-target case pass:
22P, zero failures/skips/todo. The real producer rejects four targets before
writing; its actual five invocations all use Node, not an OpenSSL executable.
A poisoned nonexistent OpenSSL environment value is present throughout.
An independent Python cryptography check validates all three signatures,
keys, validity, SANs, CA/key-usage/authority identifiers and wrong-issuer
refusal. Its six allocated synthetic files are removed after verification.

## Complete input closure and pending acceptance

The factory belongs in builder COPY, both explicit context allowlists and the
deployment dirty-input fence. Reconcile mobile WEB_PATHS, both workflow event
triggers, exact literal inventories and real fingerprint byte-change/missing
input controls. Three independent omission controls and modified/untracked
real-Git controls must pass in the complete deployment rehearsal.

The intended frontend inventory is3249/316: prior3248 plus one new case.
The affected API inventory is1704: retain all1699 earlier identities and add
three factory-omission plus two native-Git cases. Existing probe omission
test names/signatures remain unchanged. These totals need fresh native proof;
focused22P does not certify the complete candidate.

Current full frontend/compilation, all13 API shards, actual platform
complements, PG32, security/review, native browser and a fresh canonical Docker
gate remain required. OldDocker07 remains its source-bound baseline only.
Serving-release production QA and two clean post-QA maintenance executions
(second zero rebuild) must precede the canonical guarded projection resume.

External evidence in merge161001:
pr627-578b-windows-job135761460466.log,
pr627-node-certificates-focused01-receipt.json and its native/timing files,
pr627-node-certificate-independent-der01.json.
The local frontend06 npm30s preparation failure remains incomplete before
compilation;95% memory use is context, not a proven cause. The optional image
backup was conservatively stopped after a17GiB Docker capacity measurement;
no existing images, containers, volumes or retained data were removed.

References: https://www.rfc-editor.org/rfc/rfc5280.html and the native Node22
X509Certificate API. No production certificate authority or legal-policy
approval is created by this test fixture.
