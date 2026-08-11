# Manual Matter Forum Catalog — 11 August 2026

## Purpose

This file records the provenance and product interpretation of
`Manual_Matter_Creation_Enhancement_Ram11Aug2026.docx`. The enhancement requires
manual Matter creation, Matter editing, and bulk imports to use one active forum
catalog and to reject invented catalog selections.

## Catalog additions

| Product category | Exact choices added by this change | Stored lineage |
| --- | --- | --- |
| DRAT / DRT | DRAT, DRT-1, DRT-2, DRT-3 | `DRAT / DRT > Delhi > <choice>` |
| Recovery Forums | PO, Registrar, Recovery Officer | `Recovery Forums > Delhi > <choice>` |
| NCLAT / NCLT | NCLAT, NCLT | `NCLAT / NCLT > <choice>` |
| TDSAT | TDSAT | `TDSAT > New Delhi` |
| Appellate Tribunal | ED, FEMA, NDPS | `Appellate Tribunal > <choice>` |
| District Commission — Delhi | Dwarka, Janakpuri, Qutub, ITO, Kashmiri Gate, Tis Hazari | `District Commission > Delhi > <choice>` |

The six Delhi District Commission location labels are requirement-backed
choices. They supplement, rather than replace, the official e-Jagriti district
commission master already present in CaseOps. Existing consumer entries are
retained and their display lineages are normalized to NCDRC, State Commission,
or District Commission so the three levels are distinct in the UI.

## Primary-source cross-checks

- Department of Financial Services DRT/DRAT portal: <https://drt.gov.in/>
- NCLT benches: <https://nclt.gov.in/national-company-law-tribunal-benches>
- NCLAT: <https://nclat.nic.in/about-NCLAT>
- TDSAT: <https://www.tdsat.gov.in/Delhi/Delhi.php>
- Appellate Tribunal under SAFEMA: <https://atfp.gov.in/about.html>
- NCDRC: <https://ncdrc.nic.in/history.html>

## Product invariants

1. A catalog selection persists its immutable catalog ID plus the derived
   forum level, exact name, state, district, city, and consumer tier.
2. The API re-resolves the catalog ID; it never trusts client-supplied derived
   metadata.
3. New specialist and consumer bulk categories resolve through the same active
   catalog as manual creation. Unknown, inactive, mismatched, and ambiguous
   selections are row errors and cannot be committed.
4. Legacy CaseOps bulk templates using canonical enum tokens, or the historical
   Supreme/High/District Court labels with no exact catalog selection, remain
   readable. Exact common-court names are upgraded to catalog IDs; the narrow
   compatibility path cannot supply or spoof a catalog ID.
5. The downloadable XLSX template includes the live active catalog so the
   import reference cannot silently drift from the manual selector.
