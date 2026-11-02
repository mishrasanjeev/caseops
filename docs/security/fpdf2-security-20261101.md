# fpdf2 2.8.9 merge reconciliation

The merged API source pins fpdf2 exactly to 2.8.9, retaining canonical main’s complete official lock record. This supersedes the shipping-version references in the [dated 2.8.8 review](fpdf2-security-20261027.md); that review and its original bundle remain historical evidence. The two recorded advisories identify 2.8.8 as their first patched release. Their patched-version provenance is retained unchanged.

## Official inputs and attribution

The [official PyPI 2.8.9 metadata](https://pypi.org/pypi/fpdf2/2.8.9/json) and both downloaded artifacts agree with the merged lock:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| fpdf2-2.8.9-py3-none-any.whl | 341268 | 6e1d94af6d6311950a23dec7fb5fc84b000203eb59aee8e76c1e701b12a14976 |
| fpdf2-2.8.9.tar.gz | 380865 | 5b0b3786f5236a2b3cc83c1fee567df17ddd314f8c4e13d820d8f09b617ab4f0 |

The source PKG-INFO and wheel METADATA are byte-identical: 88801 bytes, SHA-256 42f92137144bb4e3b855de9b788b1db040aaf087b72baa5b3b8739b5dd475182. Both retain LGPL-3.0-only and LICENSE. The exact upstream LICENSE remains 7632 bytes, SHA-256 f97bc4bb9b7ae8a653941073678b5c7775e8de44a01c3bcc21e7cdc148b90e61. The unchanged supplemental GPLv3 text is reused from the reviewed 2.8.8 bundle with its original provenance; no new GNU fetch or fpdf2 archive membership is claimed. The 2.8.9 identity is established by PyPI and exact locked artifacts. No Git tag commit or signature verification is claimed for 2.8.9.

The new six-file bundle is apps/api/vendor/fpdf2-2.8.9. Docker copies it to /usr/share/doc/caseops-api/third-party/fpdf2-2.8.9 and runs its strict installed metadata/license verifier after locked installation. Only version-specific pins and notice/provenance bytes changed in the verifier; bounded descriptor, namespace, link and metadata fences remain. Canonical LF attributes cover all five text members and preserve the source archive as binary. The existing packaging regression verifies both upload allowlists and the deployment dirty-input fence for every new bundle member. No JavaScript exception, upstream-notice inventory or public JavaScript notice bundle changes are required for this API-only Python dependency.

## Verification scope

A dedicated private Python 3.13.17 environment installed the official 2.8.9 wheel and exact nine parser/test dependencies from the merged lock, offline and without scripts or changes to the shared API environment. Actual uv pip check and the installed bundle verifier passed. The complete existing PDF parser/security and packaging modules passed: 22 cases and 13 subtests. These include all six external-resource denial paths with zero observed file/HTTP reads, actual SVG depth and expansion limits, and successful in-memory images independently rendered through PDFium. The source-bound dependency floor function also passed against the actual private installed distribution and merged manifest/lock. The unrelated imports and tests in the broader dependency-security module were not represented as executed by this isolated component.

The initial isolated component’s generated-output audit refused a pytest-created internal current-directory symlink after those commands passed. That original refusal is retained. A separate bounded retained-only reconciliation records its exact owned target, the three interpreter links, complete generated and receipt inventories, source readbacks and process closure; it does not turn the original component into a whole-deadline pass or rerun its commands.

A fresh whole-lock advisory check, actual rebuilt image inventory/uv pip check, fresh installed-image advisory result, complete image licence/notices checks and ordinary image controls remain required for the merged published head. These source and private-runtime results do not certify a shipping image, hosted CI, deployment or native acceptance.
