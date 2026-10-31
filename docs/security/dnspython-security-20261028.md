# dnspython 2.9.0 API dependency remediation

The fresh whole-lock audit of the retained 2.8.0 candidate failed for
[GHSA-45c3-73f7-pv4m](https://github.com/rthalley/dnspython/security/advisories/GHSA-45c3-73f7-pv4m)
(CVE-2026-114605). Upstream identifies versions below 2.9.0 as affected and
2.9.0 as patched. The targeted lock regeneration changes only dnspython and its
official artifacts. No dependency override, exception or audit exclusion changes.

The [official release](https://github.com/rthalley/dnspython/releases/tag/v2.9.0)
resolves to commit `e790c8f20a67ad439c7aafef2321e161c6028eee`; its security fix is
`b485e460c266540a1a09ca6d8d1d7b685b1d3023`. The tag binding records the public
GitHub API response; it is not an independent signature verification.

The [PyPI response](https://pypi.org/pypi/dnspython/2.9.0/json) pins these inputs:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `dnspython-2.9.0-py3-none-any.whl` | 354822 | `9a4aedb833c3c1b49214d04d44d3032ab7a9135f7c1d29a549b4ff78fd82fda9` |
| `dnspython-2.9.0.tar.gz` | 423560 | `b44dc6b18f07a8b1c56676a19fbfdb5209415b046a9cece286baafa87ff3f7f1` |

Both downloaded official archives omit license/notice files despite declaring
ISC. The exact tagged upstream `LICENSE` is retained in
`apps/api/vendor/dnspython-2.9.0`: 1526 bytes, SHA-256
`c3ea3ff5654b329c19d3bc5f7481af623c3dded4a6145585499f843ad3d741cd`.
It includes the Dnspython Contributors, Nominum and Google copyright notices.
The API image explicitly copies this license, supplemental notice and provenance
to `/usr/share/doc/caseops-api/third-party/dnspython-2.9.0`. Library code remains
unmodified and installed from the official hashed wheel. Both API upload
contexts include these files; the deploy dirty fence covers all of `apps/api`,
including untracked files. Canonical notice bytes are pinned to LF in Git.

Python 3.13 meets upstream's Python >=3.11 contract. The current email-validator
edge requests no dnspython extras, and the default distribution adds no runtime
dependencies. Upstream's optional DoH extras now use httpx2/httpcore2; those extras
are not selected by this application. Ordinary offline DNS wire roundtrips,
normal response compression and email-validator compatibility are tested against
the actual installed distribution and its exact parser/metadata bytes.

The earlier unsupported old-version parser diagnostic did not reach parser
execution. That reproduction boundary remains unverified and is not used as
security acceptance. No attack or stress reproducer is part of this repair.
Official artifact provenance and ordinary compatibility are separate from a
fresh whole resolved-lock/actual-installed advisory check. A local source pass
does not certify a rebuilt Linux image, native acceptance, hosted checks or
release approval. Those gates must bind their actual final installed inventories.
The JavaScript package graph, public JS notices and historical exception
registries are unchanged; this notice belongs to the API Python image.
