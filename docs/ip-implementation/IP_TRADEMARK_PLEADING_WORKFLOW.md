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

## Lawyer-controlled lifecycle

The opposition workspace exposes create, generate, immutable manual revision,
submit, request changes, approve, finalize, source-manifest inspection, and
authenticated DOCX export. Manual edits copy the prior immutable manifests and
reset review. Approval fails closed with zero verified authority citations.
Finalization is terminal.

Routes require both the relevant IP and drafting capability. Docket access and
tenant target constraints are enforced in the service and database.

## Remaining adjacent work

IPLF-046 owns pleading consistency, placeholder, exhibit, and deeper source
validation. IPLF-047 owns the legal-SME fixture pack and UAT automation. This
workflow does not claim those slices, filing-provider integration, registry
submission, legal acceptance, or autonomous filing.
