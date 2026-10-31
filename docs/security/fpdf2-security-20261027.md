Historical evidence: the current merged source pins fpdf2 2.8.9; see [the 2026-11-01 update](fpdf2-security-20261101.md). The dated 2.8.8 results below are retained unchanged.

# fpdf2 2.8.8 API dependency remediation

The retained 2.8.7 dependency audit is a failed security result. Upstream names
2.8.8 as the patched release for external image resource access
([GHSA-rw7v-4hrq-x6r9](https://github.com/py-pdf/fpdf2/security/advisories/GHSA-rw7v-4hrq-x6r9),
CVE-2026-114609) and SVG expansion exhaustion
([GHSA-wqw6-wpr3-45rh](https://github.com/py-pdf/fpdf2/security/advisories/GHSA-wqw6-wpr3-45rh),
CVE-2026-114610). Resource access controls and SVG complexity limits address
different boundaries; blocking network access alone is not an SVG work bound.
The application policy and functional security regressions are maintained with
the dependency update, separately from this artifact/license packaging check.

## Exact upstream inputs

The [PyPI 2.8.8 response](https://pypi.org/pypi/fpdf2/2.8.8/json) identifies:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `fpdf2-2.8.8-py3-none-any.whl` | 337000 | `3557a478fc577a929c94aace9666aed4dcc432b5ab6764232e6a59f1ccd75f17` |
| `fpdf2-2.8.8.tar.gz` | 374689 | `9e94e155e85e8053329a9a1fce8b566fd7a7c5bb79e98a1a3952d379b947c5b9` |

The [upstream release tag](https://github.com/py-pdf/fpdf2/releases/tag/2.8.8)
resolves through GitHub's tag API to commit
`e1fc653d8fce65d2fb118755bda8581a9bf1e4d9`. This records the API-observed tag
binding, not an independent cryptographic verification of GitHub's signature UI.
Exact artifact URLs and selected archive-member identities are in
`apps/api/vendor/fpdf2-2.8.8/provenance.json`.

The wheel `METADATA` and source `PKG-INFO` are byte-identical: 86026 bytes,
SHA-256 `b7d0e7d8c32104ca54bec2e3d8744e8529eae9182c58113d650cbb0ae7eaa9b2`.
Both declare `License-Expression: LGPL-3.0-only` and `License-File: LICENSE`.
The wheel and source license texts are also identical: 7632 bytes,
SHA-256 `f97bc4bb9b7ae8a653941073678b5c7775e8de44a01c3bcc21e7cdc148b90e61`.
The dependency was already LGPL-3.0-only in the retained 2.8.7 metadata; this
update does not introduce an MIT-to-LGPL relicensing. The inaccurate MIT comment
in `matter_summary_export.py` is corrected without a behavior change.

## API packaging and replacement

The API image contains the unmodified source archive, exact upstream `LICENSE`,
`NOTICE.txt`, provenance and the supplemental full GPLv3 text at
`/usr/share/doc/caseops-api/third-party/fpdf2-2.8.8`. The GPL text is from the
[GNU Coreutils 9.8 source](https://github.com/coreutils/coreutils/blob/v9.8/COPYING),
35149 bytes, SHA-256
`3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`.
It is explicitly supplemental, not represented as an fpdf2 archive member.

`verify.py --installed` runs after the locked Python installation. It checks
the retained source/license bytes and the installed distribution's exact
version, wheel metadata and license through bounded descriptor reads. It does
not import fpdf, execute the source archive, contact an external service or
install another package. The unmodified Python library remains separately
replaceable in a recipient's image; its source and notices travel with the API
image rather than relying on a public web notice to supply them.

Both API upload contexts already include the vendor directory: the build uses
`apps/api`, with its own `.dockerignore` and `.gcloudignore`. The deployment
dirty-input fence includes all of `apps/api` and untracked files. The API
Dockerfile now explicitly copies this complete directory. The repository-root
web context, JavaScript exception registry, upstream/notice inventories and
public JavaScript notice bundle remain unchanged; fpdf2 is not a JS dependency.

## Evidence boundaries

The old and new wheel/source archives, original PyPI and GitHub responses,
selected metadata/license bytes, and the initial GNU-text fetch timeout are
retained outside Git. The committed unmodified 2.8.8 source archive and pinned
metadata are sufficient for the offline packaging controls; those tests use no
network or installed fpdf runtime. A packaging pass is not a fresh whole-lock
audit, a rebuilt image, hosted CI success, native acceptance, or a shipping
approval. Those replacement checks must bind the final corrected source and
actual installed inventories before release. Historical failed/native evidence
is retained separately.
