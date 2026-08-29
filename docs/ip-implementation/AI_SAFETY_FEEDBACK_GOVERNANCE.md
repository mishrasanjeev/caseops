# AI Safety And Feedback Governance

## Scope

IPLF-065 closes two bounded responsibilities:

1. a deterministic, CI-blocking safety evaluation over every approved legal-AI
   surface; and
2. one tenant-scoped human-feedback queue for Product Guide results and
   creator-private Workspace Assistant answers.

It extends the existing Product Guide, Workspace Assistant, audit,
`EvaluationRun`/`EvaluationCase`, membership-capability, and legal-source
owners. It does not create another help corpus, assistant conversation store,
research index, legal-source registry, model-run store, analytics pipeline,
prompt updater, domain writer, worker, scheduler, or provider benchmark.

## Canonical Feedback Record

`ai_feedback_items` owns the feedback lifecycle. A row contains:

- tenant, submitter, reviewer, idempotency key, and timestamps;
- one approved surface and canonical target reference;
- either helpful/not-helpful rating or typed report category;
- bounded optional user comment and admin review notes; and
- normal/high priority plus open/in-review/resolved/dismissed status.

It deliberately does not copy a guide query or content, assistant prompt or
answer, citation, document text, source snippet, retrieval payload, model
output, or provider payload. Canonical references are resolved through their
existing owner when authorized.

The additive migration has tenant-bound submitter/reviewer foreign keys,
idempotency uniqueness, payload/lifecycle checks, bounded review indexes, and a
fail-closed downgrade while retained rows exist. No backfill or alternate
writer is required.

## Submission Contracts

Authenticated users may submit:

- `POST /api/ai-feedback/product-guide`; and
- `POST /api/ai-feedback/workspace-assistant`.

Product Guide submission requires the current server-owned fingerprint and an
existing command, section, permission, or no-match target. Assistant submission
requires an assistant-role turn in a session created by the same active
membership and company. Stale, invented, user-turn, cross-session, and
cross-tenant targets fail closed.

Each `(company, submitter, submission_key)` is idempotent. An exact retry
returns the original record; reuse with different semantic content returns a
conflict. Unsafe-citation and missing-permission-explanation reports are
automatically high priority.

## Review Contract

Only a membership with `workspace:admin` may list or review feedback through:

- `GET /api/admin/ai-feedback`; and
- `PATCH /api/admin/ai-feedback/{feedback_id}`.

Listing is tenant-scoped, filterable, ordered, and bounded to 100 rows. Review
uses the row timestamp as an optimistic-concurrency token. Open feedback may
move to in-review, resolved, or dismissed; in-review may move to resolved or
dismissed. Resolved and dismissed rows are terminal and cannot reopen.

Audit actions `ai.feedback.submitted` and `ai.feedback.reviewed` contain only
surface, feedback type/category, priority, and status metadata. Comments,
review notes, target references, prompts, answers, citations, and source
content are excluded from audit metadata.

## User Experience

The Product Guide exposes rating/report controls on command, section,
permission, and no-match results. Workspace Assistant exposes them only on
assistant answers. Rating and report submissions are independent and retry a
failed request with the same idempotency key.

The existing admin area links to a responsive review queue with bounded filters,
status, priority, category, target reference, user comment, and review notes.
The control group and queue are verified at 360px as user-visible surfaces, not
only DOM presence.

Feedback does not modify a prompt, catalog, answer, source, model, or domain
record. Any product/model change remains an explicit reviewed code or policy
change and must pass the safety release gate again.

## Safety Evaluation Gate

`caseops-eval-ai-safety --release-gate` reads checked-in schema-v2 fixtures and
requires complete coverage for drafting, citation validation, Matter File Q&A,
recommendations, Litigation Strategy, hearing packs, Workspace Assistant, and
intelligent review. It blocks failures in citation entailment, source access,
authority relevance, contrary authority, abstention, permissions, prompt
injection, prohibited outputs, statute confusion, fact fabrication, or data
exfiltration.

The machine result is redacted. An approved caller can persist that result
through the existing evaluation tables; no second evaluation store is added.
The same release-gate command runs in CI. Live-provider benchmarking remains a
separately approved non-production activity and is not implied by a green
offline gate.

## Verification And Release

Repository proof must include migration upgrade/downgrade behavior, tenant and
creator isolation, capability enforcement, target validation, idempotent replay,
optimistic review, terminal-state immutability, audit redaction, each safety
detector, complete release coverage, canonical evaluation persistence,
component behavior, API/web type checks, and the dated 360px browser journey.

Release proof must use the exact committed production API/web images against a
fresh PostgreSQL/Valkey Docker environment before publication. Production
activation then requires green CI/Security/CodeQL, migration-first deployment,
complete index health, exact API/web release identity, dated hosted acceptance,
post-route health, and canonical `main`/`origin/main` equality. Protected
schedulers are unrelated to this slice and must remain paused.
