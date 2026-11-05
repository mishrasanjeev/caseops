# BUG-016: preserve original invoice text in PDFs

**Not fixed; implementation awaiting verification and production acceptance.**

The canonical mapping is **J11 / M10 (billing), US-032/US-033, FT-056**.
The October 31 report's J11/M11 label is mapping drift: canonical M11 covers
clients/KYC. Adjacent PDF paths cover FT-019/FT-066; legibility, offline
availability, licence retention and source integrity concern NFT-013/014/017.
Tenant, invoice capability and financial/lifecycle rules remain unchanged.

## Observed failure and root cause

Production revision `bdd1480699222712475372690334659088629429` failed the
original reported-invoice line-description assertion. Diagnostic run
41746670644 reached that body: the first reported invoice's first line had
29 source characters, failed the raw PDF-text comparison, and matched only
after the current renderer's typography translation. One character changed;
NFKC did not explain the difference. Only hashes, lengths and boolean flags
were retained. The second reported invoice and later assertions were not
reached and remain unverified.

The shared renderer deliberately changed smart punctuation and the rupee
sign and replaced unsupported character runs. Three adjacent export helpers
also flattened text. This changes legal/business source content during
export. Existing invoice rows do not need a rewrite or migration.

A controlled, offline negative baseline reached **all 27 test bodies**:
27 call failures, 54 passing setup/teardown phases, zero skips/errors, native
pytest exit 1 within the original 120-second acceptance bound. The unchanged
tests cover source-string identity, actual PDF extraction, the three core
families' four styles and wrapped tables/pairs. An earlier hostname-denial
setup failure reached zero bodies and is retained separately. Evidence lives
under `outputs/mac-release-closure-20261103/prodM-bug016-negative02/`;
its manifest SHA256 is
`27bcc69385a132dcf9164a357536584513a52f1e8c51bed0a2503e99eb0bb618`.

The first positive attempt reached all27 bodies:20 passed and seven wrapped
table calls failed, with all54 setup/teardown phases passing and no skips.
The native table checks a bold heading's font key before calling set_font;
the adapter had registered only the current regular core face. The correction
registers all four genuine faces of the selected family before table admission.
Twelve adjacent actual-table render/extraction cases cover Helvetica, Times
and Courier with regular, bold, italic and bolditalic initial bodies. The
original27-case source and its120-second bound remain unchanged. The first
replacement plan was27 cases then45 integrity+9 packaging cases, each focused
component retaining120 seconds. The failed attempt and unexecuted original
42-case packet remain retained.

The four-face replacement subsequently passed all27/81 phases (native0).
Its adjacent54-case run reached41passes/13call failures with all162 phases
complete and no skips: twelve mixed-script table cases and the real
immutable-parser/shaper case exposed an extra U+0004 in extracted text.
Three retained synthetic PDFs proved the boundary: a real Devanagari
continuation glyph had CID4 and no logical Unicode tuple; its ToUnicode CMap
omitted that CID and PDFium returned U+0004 from the same font. Hindi-only
and Latin-only controls did not exhibit it. These failures are retained.

The subsequent semantic correction wraps only ordinary shaped
fragments in PDF1.5 inline ActualText, using their original logical text as
UTF16BE hex with BOM. It delegates all glyph-rendering operators unchanged,
preserves fragment clones/state/links and leaves special page-count fragments
intact. No glyph Unicode is invented, source/control characters are not
stripped, and HarfBuzz stays enabled. Its initial focused replay plan was the
unchanged27 cases, then45 integrity+9 packaging+6 semantic cases (60), each
under the original120-second component bound. Exact pixel comparison against
the same three retained synthetic PDFs has subsequently passed. Raw FPDF.text() is
outside this fragment hook; none of the five current generators calls it.

Reader interoperability is separately open: pdfminer and the original
invoice checker's pdfjs path must be checked rather than inferring their
behavior from PDFium or the PDF standard. ActualText alone is not a claim
that every parser honors semantic replacement.

The semantic renderer's unchanged27-case replay subsequently passed27/81.
The first60-case semantic component reached55passes and five instrumentation
TypeErrors (all180 phases complete, zero skips). All original45 integrity
and nine packaging cases passed, including the thirteen earlier extraction
failures. The five new cases had already passed source/no-U+0004 checks;
they then tried to convert the SDK's finalized PDFContentStream object
directly to bytes. Their remaining stream-inspection assertions were not
reached. The test-only successor uses the actual content_stream() API and
bounded decompression for its declared FlateDecode filter, with three
unknown/corrupt/oversized native-stream refusal cases. All original assertions,
font code,27-case and45-case sources remain unchanged. The replacement63-case
component passed all189 setup/call/teardown phases with native0, no skips or
errors, in8.092 seconds under its original120-second bound. Its45 integrity,
nine packaging and nine semantic cases all completed. The unchanged27 cases
were not rerun to repair the inspection instrumentation.

The same-three-PDF comparison also passed under its original60-second bound:
each old/new RGB pixel buffer was exactly equal (2,353,455 bytes per page).
The mixed, Hindi-only and Latin-only samples preserved their original source
text in PDFium without the previous control characters. Root independently
read all producer evidence through87 stable binary descriptors, reconciled
the63-case/189-phase inventory and confirmed the four known processes absent.
This is synthetic offline evidence, not the original invoice workflow.

The original invoice decoder was then exercised unchanged against the same
three samples. Its installed PDFjs5.4.296 preserved Latin typography, rupee
text and all three amounts, but mixed/Hindi text still contained U+0004/U+0003.
The native check correctly failed. No control characters were stripped and
no source expectation or decoder was changed. Mozilla's open
[ActualText support issue](https://github.com/mozilla/pdf.js/issues/12237)
provides upstream context; the local pinned-decoder failure is the evidence.
Do not claim universal PDF-reader compatibility. CaseOps's own pdfminer-backed
readers are being repaired and verified separately; their recovery does not
repair external viewers or waive either original reported invoice assertion.

## Proposed product behavior

Source text stays unchanged. The five existing PDF generators use the shared
Unicode renderer: matter invoices, cause lists, matter summaries, court-format
drafts and SaaS billing. There is no new external font service.

Fourteen unmodified, pinned fonts are packaged offline: Liberation 2.1.5
Sans/Serif/Mono each has genuine Regular/Bold/Italic/BoldItalic faces, and
Noto Sans Devanagari 2.002 supplies genuine upright Regular/Bold fallback.
The Devanagari fallback keeps bold but uses an upright face for italic text;
no regular face is relabelled as italic. Exact font cmaps govern support.
This finite set does **not** cover every Unicode script. A missing glyph
refuses the export with an actionable 422 error before PDF bytes return;
the source invoice remains unchanged. It does not invent a DOCX invoice route.

`fpdf2==2.8.9` and `uharfbuzz==0.57.0` / native HarfBuzz 15.0.0 are version
bound. FontTools and HarfBuzz receive the same verified immutable bytes.
The descriptor reader keeps ordinary file/ancestor, before/after version,
cross pathname/descriptor identity/size/mtime and digest checks. No mutable
pathname is reopened by a parser/shaper. ResourceAccessPolicy.NONE remains.

Both original OFL notices, Liberation's source archive, HarfBuzz's Old MIT
COPYING and uharfbuzz's Apache 2.0 licence are retained in the API image.
Four exact public notice downloads and catalog entries expose the attribution.
The historical 19-package exception registry and 56 upstream materials stay
unchanged. The web builder admits only seven explicit API declaration/licence
inputs used by its colocated notice units; API runtime code, fonts and source
archives are excluded from the web runtime. Binary font/notice bytes are
preserved across checkout platforms.

## Verification still required

- The fresh, exclusively owned22-package PDF environment is qualified and
  remained unchanged through the27/63-case runs and three pixel comparisons.
  It does not qualify the full API or Linux image. Accepted API139/API162
  profiles were not installed into or mutated.
- Finish all five export-entry-point API paths and existing invoice
  legibility/court-profile tests, with every phase retained. The27/63 focused
  checks do not exercise the complete API/database journeys.
- Verify fonts/notices in an actual built wheel and shipping Linux image,
  exact Linux/Windows installed dependencies, fresh full advisory scans and
  native dependency health. Static Docker COPY contracts alone are insufficient.
- Complete changed frontend units/type checks have passed locally (43cases,
  whole web component and E2E TypeScript, stable input hashes). Native Docker/
  gcloud upload-closure controls and nearby private-input canaries remain open.
- Finish fresh complete candidate CI, security analysis plus alert verdict,
  canonical deployment and the original reported **two** invoices' desktop/
  mobile journeys with their original source assertions and deadlines.

No local synthetic pass, diagnostic subset or earlier release result closes
the reported production workflow. No data-governance migration is introduced;
the new materials are static distribution assets and original licence notices.
