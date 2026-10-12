# JS Dependency Compliance Review - 2026-10-12

## Disposition And Scope

The owner selected a documented compliance review, not a global license waiver.
Engineering disposition: admit the exact 19 reviewed locked packages for
operator-controlled, stock-package **managed SaaS only**, subject to the release
conditions below. No inherent commercial SaaS prohibition was found in the
reviewed terms. This is not a legal guarantee, codec patent clearance, approval
of every hosting contract, or production certification.

The existing 14-term global allowlist is unchanged. The machine-readable record
is `license-policy/reviewed-packages.json`: exact name, version, license
expression, lockfile SHA512 SRI and original material hashes. Changed packages,
license terms, notices, integrity or this review document require a fresh review.
Unreviewed identities and invalid/missing evidence remain blocked. No human
approval endpoint or provider activation is introduced.

Customer binary, installer, SDK, exported container, on-premise or redistributable
WASM delivery is **outside this disposition**. Freeze such distribution and
perform recipient, corresponding-source, relinking, installation and notice
review first. A retained GPL/LGPL text is not a redistribution compliance package.

## Exact Inventory

The reviewed families are:

| Packages | Exact Version | Locked License |
| --- | --- | --- |
| Three Fontsource packages: Atkinson Hyperlegible, JetBrains Mono, Libre Caslon Text | 5.2.8 / 5.2.8 / 5.2.7 | OFL-1.1 |
| Ten `@img/sharp-libvips-*` Darwin, Linux and musl platform packages | 1.3.4 | LGPL-3.0-or-later |
| Three `@img/sharp-win32-*` arm64, ia32, x64 packages | 0.35.5 | Apache-2.0 AND LGPL-3.0-or-later |
| `@img/sharp-wasm32` | 0.35.5 | Apache-2.0 AND LGPL-3.0-or-later AND MIT |
| `nodemailer` | 10.0.13 | MIT-0 |
| `pako` | 1.0.11 | MIT AND Zlib |

Every exact platform identity and SRI is retained in the registry. All 19 npm
archives were verified against the lock, then their original package identities
and expressions were checked. Fifty-one retained original package materials
comprise 19 manifests, 14 `@img` READMEs, four Apache license texts and 14 bundled
version manifests. No dependency version or license declaration was relabeled.

The bundled README union identifies 31 libraries: each native README lists 29,
while WASM lists 20. Native versions include libvips 8.18.7, FreeType 2.14.3,
Cairo 1.18.6 and AOM 3.15.1. WASM also identifies Emscripten 6.0.10 and resvg
0.48.1. `libnsgif` has no separate published version key; no version is invented.
Future corresponding-source delivery must trace its vendored source separately.

## Obligations And Implementation

### Distributed Fonts And JavaScript

Original copyright headers and complete OFL texts accompany the three stock
fonts at `/third-party-notices`, accessible from the public footer and as exact
same-origin downloads. Font bytes and names are not changed; fonts are not sold
alone. Preserve OFL licensing and applicable modified-font-name restrictions;
font author names are not product endorsements. OFL does not license unrelated
CaseOps application code or generated legal documents. See the
[official SIL OFL FAQ](https://openfontlicense.org/ofl-faq/).

Pako requires both MIT and Zlib terms, not a choice. Retain its complete MIT text
and the original 960-byte Zlib source-header notice, including authors and all
restrictions. Preserve truthful provenance and mark future source alterations.
The current DocxViewer dependency chain reaches Pako through JSZip; JSZip's MIT
alternative does not erase Pako's obligations. Nodemailer's original MIT-0 text
is also retained; no MIT-style mandatory attribution or invented fee is added to
MIT-0. See [MIT-0](https://spdx.org/licenses/MIT-0.html) and
[Zlib](https://spdx.org/licenses/Zlib.html).

Six original notice files and their complete visible texts/hashes are retained.
The production runner must copy `apps/web/public`; a page-only unit pass cannot
prove that downloads accompany the shipped fonts/client code. The notice page is
noindex/follow, excluded from the indexable sitemap, and adds no analytics,
tracking cookies, lead submissions, provider calls or marketing compliance claim.

### Server Image Libraries

Use the unmodified locked native/WASM packages server-side, outside public
assets and customer downloads. GPL v3 distinguishes remote interaction without
program-copy transfer from conveying and separately constrains controlled
hosting facilities. Ordinary image output is not automatically a copy of the
program. This supports the reviewed stock managed-service premise, not arbitrary
contractor distribution. Signed Google hosting terms were not audited here.
See [GPL v3](https://spdx.org/licenses/GPL-3.0-or-later.html).

LGPL v3 incorporates GPL v3 with library permissions; future combined-binary
delivery requires its actual notices, license copies and source/relink or
suitable shared-library arrangements, plus applicable installation information.
The package READMEs elect v3 through the earlier license's later-version clause.
Retain original libvips v8.18.7 LGPL v2.1 text alongside full GPL/LGPL v3 texts;
do not replace its provenance. See [LGPL v3](https://spdx.org/licenses/LGPL-3.0-or-later.html).

This product uses the FreeType project through its server image-processing
dependency bundle. FreeType credit and the original bundled documentation are
retained here and in all 13 native READMEs. No copyright year is invented.
Keep FTL's acknowledgment and any future distribution disclaimers, not a
substituted generic MIT text. See [FreeType License](https://spdx.org/licenses/FTL.html).

Cairo is identified under MPL-1.1, not LGPL or MPL-2.0. Preserve its actual
modification/source-availability and patent terms when applicable. AOM includes
BSD-2-Clause plus its separate patent license: preserve conditions, reciprocal
Necessary-Claims provisions and defensive termination. Copyright permission is
not universal codec patent freedom to operate. See
[Mozilla MPL-1.1](https://www.mozilla.org/en-US/MPL/1.1/) and
[AOM's official patent license](https://aomedia.org/license/patent-license/).

Retain original bundled documentation for the other LGPL/MIT/BSD components and
custom Fontconfig, libpng, libtiff, mozjpeg/IJG and zlib-ng terms. The four Apache
texts do not substitute for those terms or an applicable NOTICE. A top-level
SPDX summary does not constitute every future redistribution obligation.

## Release Conditions

1. Validate both exact logical workspace closure and all actual physically
   copied production packages. Windows or Ubuntu/glibc does not certify the
   pruned Linux x64 musl image; retain platform exclusions and every denial.
2. Prove the stock native/Sharp-WASM program is not delivered in public or
   emitted client assets. Do not substitute a source import search for actual
   built-image inspection. Keep private operator-controlled container delivery.
3. Execute the current public browser inventory after a fresh build, at desktop
   and mobile widths, asserting footer accessibility, full original text,
   downloadable byte hashes, noindex and non-mutating behavior. Repeat the same
   journey against the exact serving production revision.
4. Require complete combined Docker/migration/CI/security, canonical main and
   guarded exact-SHA deployment acceptance. Retain all earlier failed evidence.

Current read-only production observations show no repository/project public IAM
bindings in the inspected responses and one anonymous manifest request rejected
with 401. This is not a complete anonymous pull flow, organization IAM audit or
future-distribution certificate. Release evidence must bind the new candidate
and image, not use this old-tag observation as its identity.

## Provenance And Boundaries

Full SPDX texts are pinned to license-list-data commit
`31ba1a50e5397e00a304dbadc76531740e89ee48`; original libvips LICENSE is pinned to
commit `24ad4d042940e6bf99a68871ba886ca8847c9c82`. All original material bytes and
hashes are retained under `license-policy/upstream` or public notice assets.
The incorrect upstream `COPYING` URL's 404 remains failed acquisition evidence;
the distinct correct `LICENSE` retrieval does not overwrite it.

The independent exact-19 assessment and package/component comparisons are in
`outputs/pr-merge-release-20261012/license-compliance-independent-review` in the
original workstation repository. This document binds the scoped engineering
decision and obligations; separate release evidence records executed gates.
No provider-cost, financial-baseline, model-consent, security or legal-source
fence is weakened. Nothing here claims production release completion.
