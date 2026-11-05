# Public synthetic ActualText PDF fixtures

These are exact outputs of the renderer qualification at
`outputs/mac-release-closure-20261103/prodM-bug016-semantic-pixels-actual01`.
They contain public synthetic fee strings, genuine embedded packaged fonts,
and per-document inline ActualText. They contain no tenant or production data.

Root qualified all 63 renderer cases and proved these three raster pixel
buffers equal to their retained pre-ActualText counterparts before these bytes
were copied. Reader tests pin exact bytes and independent literal source text.
The retained original mixed PDF exposed the unmapped continuation CID4 as U+0004;
it remains historical failure evidence, not this fixture.

The original font licences and provenance are packaged under
`apps/api/src/caseops_api/assets/pdf_fonts/`. Embedding the fonts in synthetic
documents does not change those upstream font programs or notices.
