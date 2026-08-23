# Trademark Pleading Workflow

## Ownership

IPLF-045 extends the existing `Draft`, `DraftVersion`, `DraftReview`,
`ModelRun`, and drafting-provider pipeline. It does not introduce a second IP
drafting engine or a parallel recommendation store. A draft has exactly one
tenant target: either a Matter or an IP docket, with an optional proceeding
that must belong to that docket.

## Supported templates

The initial India Trade Marks Registry profile supports:

- notice of opposition for an opponent at `draft`;
- counterstatement for an applicant at `service_pending` or
  `counterstatement_due`;
- opponent evidence at `opponent_evidence_due`;
- applicant evidence at `applicant_evidence_due`; and
- reply evidence for an opponent at `reply_evidence_due`.

The service rejects templates that do not match the proceeding's represented
side, stage, or jurisdiction. Template availability is derived from the live
canonical proceeding and is rechecked on every generation.

## Generation record

Each generated revision freezes:

- template key, version, represented side, stage, jurisdiction, and format
  profile;
- confirmed identifiers, parties, events, and deadlines used as context;
- exact linked IP document-version IDs, names, states, and SHA-256 hashes;
- the provider, model, prompt hash, and generation timestamp; and
- surviving authority citations and their verification count.

Only linked document versions in an approved, filed, served, or accepted state
provide text to the model. Missing particulars remain placeholders. Provider
failure creates neither a draft version nor a `ModelRun` ledger row.

## Deterministic validation

IPLF-046 adds deterministic checks to the shared drafting owner. Generation
fails closed when required application or opposition identifiers are missing or
conflict. Approval and filing recheck the frozen revision against current
canonical proceeding, identifier, deadline, authority, and IP document-version
records. A blocker is emitted for:

- unresolved square-bracket, moustache, or angle-bracket placeholders;
- a changed proceeding stage/version, identifier set, or captured deadline;
- a previously verified authority that is no longer available;
- a missing document version, changed SHA-256, or source that left an approved,
  filed, served, or accepted state;
- a `[SOURCE:<document-version-id>]` or
  `[EXHIBIT:<document-version-id>]` anchor outside the frozen manifest; or
- an Annexure/Exhibit reference without an exact exhibit anchor.

Conflicting dates for the same sourced registry event remain mandatory warnings
for lawyer resolution. The validation endpoint returns the exact blocker and
warning counts used by the approval and filing gates; the UI does not maintain
a second interpretation.

## Lawyer-controlled lifecycle

The opposition workspace exposes create, generate, immutable manual revision,
submit, request changes, approve, finalize, source-manifest inspection,
revision comparison, authenticated DOCX export, and a filing bundle. Manual
edits copy the prior immutable manifests and reset review. Approval fails closed
with zero current verified authority citations or any validation blocker.

Finalization locks the revision but is not treated as filing. `file`,
`reject_filing`, and `serve` are distinct human actions on `DraftReview`, with
the acted-on immutable version ID, external reference, event time, optional
service method, actor, and notes. A rejected filing reopens editing; the
corrected body becomes a new version and the original filed version/event is
not rewritten.

The filing ZIP places the Registry-formatted, page-numbered DOCX under
`filed-document/`. The template/model/context/source and validation manifest is
kept separately under `internal/generation-manifest.json`; the internal filing
checklist is also outside the filed document.

Routes require both the relevant IP and drafting capability. Docket access and
tenant target constraints are enforced in the service and database.

## Remaining adjacent work

IPLF-047 adds a versioned, synthetic legal-fixture pack, executable mappings to
the canonical API tests, tamper-evident content hashes, and a fail-closed legal
approval gate. The committed pack is an engineering candidate and cannot be
used as authoritative legal UAT evidence until distinct reviewers approve its
exact source and content hashes.

This workflow does not claim filing-provider integration, direct Registry
submission, legal acceptance, or autonomous filing. Filing and service are
records of human-controlled external actions, not provider-side automation.
