# dnspython WKS dependency update — November 14, 2026

QG-SEC-004 / NFT-005, J14/M14 release verification. Candidate implementation;
production closure **Inconclusive**, complete native release **NO-GO** pending
the exact updated image, strict installed audit, CI and native acceptance.

## Actual failure and upstream identity

PR612 Security run43520469887 failed on source4ca30702 after `uv pip check`
confirmed all138 installed packages compatible. Its strict OSV audit found
dnspython2.9.0 affected by CVE-2026-128089 / GHSA-vvf4-9x63-8xvv. Preserve the
failed job, rather than rerunning the unchanged lock or excluding the advisory.

The [maintainer advisory](https://github.com/rthalley/dnspython/security/advisories/GHSA-vvf4-9x63-8xvv)
identifies a missing WKS service-number bound and names2.9.2 as patched. The
[upstream fix](https://github.com/rthalley/dnspython/commit/388db14ee9923288f6e73f86e482c77706e59d73)
also limits directly constructed/wire-read bitmaps to8192 bytes. The reviewed
test uses small, bounded inputs; it never attempts memory exhaustion. This does
not establish a CaseOps route accepting attacker-controlled zone-file text.

The [official PyPI release](https://pypi.org/project/dnspython/2.9.2/) binds its
publishing commit to854bedd6d641cb42785d26ca674ed2c0f20131e0:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| dnspython-2.9.2-py3-none-any.whl | 360455 | af15f7d385a6ae2fb35a796fde2138004c8c42c7389090e2addc83e3b3340fd8 |
| dnspython-2.9.2.tar.gz | 455484 | 8d4d39a513e649d634004ce4d39ade2352efcea472a0247535a5c2d18a9d7ba9 |

## Change and adjacent-path checks

Raise the API floor to2.9.2 and regenerate only that package's resolution and
project requirement metadata in the DNS-only lock comparison. The separately
documented [telemetry repair](otel-security-20261114.md) updates its own cohort.
The resolver also rewrote unrelated uharfbuzz
timestamp precision and omitted ten older PyPy wheels. Its generated output is
retained; restore the exact pre-existing uharfbuzz record after proving its
version and every common artifact URL/hash/size unchanged. The resulting lock
passes canonical `uv lock --check --offline`. Every other parsed package record
remains equal, including the reviewed FastEmbed source override.

Both official2.9.2 archives include their ISC license. Their license bytes match
the tagged source and the1526-byte image notice, SHA-256
c3ea3ff5654b329c19d3bc5f7481af623c3dded4a6145585499f843ad3d741cd.
Bind METADATA, the name parser, WKS parser and installed wheel license in the
new provenance. Update the exact Docker COPY and LF attributes, and verify both
API upload contexts and the existing API-directory deployment dirty fence.
Keep2.9.0's dated provenance/notices and prior advisory history unchanged. The
JavaScript notice inventories and exception registry are separate and unchanged.

## Executed local evidence and remaining gates

`apps/api/tests/test_dnspython_wks_security_20261114.py` runs ten offline tests.
On the unmodified official2.9.0 wheel it fails six assertions, including the
maintainer's first out-of-range service, named-service bounds, direct bitmap
construction and wire parsing. All ten pass on the hash-verified2.9.2 wheel.
Valid0/65535 service bits, empty/maximal bitmaps, named services and exact wire
roundtrips remain covered; network calls are refused.

The complete updated dependency identity/notice/integrity module, new WKS module
and shared fpdf packaging module pass40 cases plus17 subtests, zero failures or
skips, using the actual unmodified wheel. Ordinary compressed DNS responses,
following-field boundaries and email-validator without DNS networking remain
covered. This first selection uses a scoped parser environment. A second complete
four-module selection passes53 cases plus17 subtests with normal API fixtures
in the actual locked Mac API environment, including the observability extra;
zero cases fail or skip. Installed dependency validation also passes. The later
combined selection passes112 cases plus22 subtests and the strict audit of all152
installed Mac distributions passes after the telemetry repair. Independent
Linux/image and native evidence remain pending.

Evidence is retained under the owned native evidence root in
`dnspython292-security-20261114-01/`: original CI job, official metadata/artifacts,
red/green logs, exact lock reconciliation and native JUnit results. Full API
installed dependency validation, strict fresh audit, new image/CI and native
application proof remain required. Neither this dependency fix nor the earlier
source4ca Android compile grants a native83-case pass or store approval.
