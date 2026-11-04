# PDF reader recovery for shaped Unicode exports

Status: Inconclusive. Source prepared; native qualification and deployed workflow acceptance remain pending.

This adjacent BUG-016 repair maps to J04/M03/MOD-TS-002, US-007 and US-009,
FT-009/011/012, and J05/US-010/FT-020. It preserves uploaded source text for
search and prevents an undefined Unicode mapping from being indexed as a
synthetic `(cid:N)` marker. SEC-005/006/015 upload, malware and tenant boundaries
remain owned by the existing callers. No database, provider, corpus ingestion,
embedding, language, minimum-character or benchmark policy changes are made.

The renderer's per-document ActualText span is standards-correct, but the
pinned pdfminer.six 20260107 normal TextConverter ignores marked-content
replacement text. The original invoice checker also uses pdfjs-dist 5.4.296;
its getTextContent path is a separate acceptance boundary. This change does
not switch or weaken that invoice oracle and does not claim all PDF readers
support ActualText.

The shared API reader reproduces the existing pdfminer extract_text defaults
and records actual undefined-glyph callbacks per invocation. Healthy output is
returned exactly, including literal business text `(cid:4)`. Only a real
undefined event, an empty result or a parser error selects a whole-PDF PDFium
recovery. Both engines read the same opened source; pathname and descriptor
versions are independently fenced. Password/extraction-policy and memory
refusals never authorize a different engine. Recovery checks native Unicode
mapping errors and invalid text controls, and preserves the independently
mapped character counts (including amounts) before accepting a recovery.
These are failure/conservation checks, not a guarantee of legal or OCR accuracy.
It does not delete or replace any source text. Empty or failed recovery remains
on the existing OCR/failure path.

The three integrations are document processing, local corpus PDF parsing and
court-sync byte parsing. Their upload/download limits, page and time policies,
Docling preference, OCR thresholds, corpus 4000-character floor, language,
Layer-2, Voyage and source/authorization policies remain unchanged. No corpus
job or retrieval rating is part of this task.

Regression scope includes ordinary complete-output equality to the pinned
extract_text, literal CID text, same-source multi-page recovery, empty/scanned
PDF, first-error retention, security refusal, invalid or worse fallback,
native-handle closure, source drift, three caller paths and Docling preference.
Three exact qualified shaped-PDF fixtures are pinned after the renderer's
63-case and three-buffer pixel qualification. No HarfBuzz rendering is required
in the borrowed read-only API139 test environment. A shared process-wide mutex
also serializes the new reader and both existing native OCR render lifetimes;
Pillow pixels are detached before native bitmap closure. DPI, page limits,
language/provider selection and OCR thresholds retain their original values.
Deterministic fake-native two-thread controls prove each pair of the three
actual call paths enters the same lock and closes native documents before the
next enters. They do not perform concurrent PDFium calls.

SOURCE02 is also retained unexecuted. Source review found that reading the
whole opened PDF into bytes added an allocation to the uncapped per-PDF corpus
path. The successor passes the same still-open seek/read/readinto stream to
PDFium with `autoclose=False`. Native document closure precedes source-owner
closure. A real native sized-read witness refuses unbounded reads and checks
both normal recovery and source drift; existing byte and page assertions remain.

The first closed SOURCE01 packet is retained unexecuted. Its independent peer
identified that parser failure discarded already-mapped prefix observations.
The successor retains both the original parser exception and those character
counts, and refuses a recovery that loses them, before any new test execution.

Primary references: [pdfminer 20260107 device callbacks](https://raw.githubusercontent.com/pdfminer/pdfminer.six/20260107/pdfminer/pdfdevice.py),
[PDFium Unicode mapping error API](https://pdfium.googlesource.com/pdfium/+/refs/heads/main/public/fpdf_text.h),
and [ISO 32000-1 replacement text, section 14.9.4](https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/pdfstandards/pdf/PDF32000_2008.pdf).
