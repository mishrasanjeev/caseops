# IPLF-066B private retrieval workflow

## Outcome and activation boundary

IPLF-066B connects Workspace Assistant and the private-search API to the one
`private_retrieval` owner established by IPLF-066A. It adds bounded tenant
projection workers and safe integrity inspection without creating another
source writer, ACL registry, answer writer, public corpus, queue, or manual
approval gate.

Private retrieval is fail-closed. Every consuming request re-resolves the
active company, user, membership, `ai:generate` capability, `workspace_core`
IP entitlement and rollout, and tenant Workspace Assistant policy. The browser
cannot activate the feature with a flag or tenant identifier. When this
activation decision is true, private document text cannot fall back to the
legacy direct-extraction path; a missing, lagging, stale, ineligible, or
tombstoned projection produces abstention.

## Consumer and query contract

`POST /api/private-retrieval/search` accepts a bounded query, closed source
types, optional typed scopes, locale, and a maximum of 20 results. It invokes
the canonical SQL prefilter before ranking. The response has no total, facet,
or “more results” indicator from which restricted candidates could be inferred.

The same owner exposes three deliberately narrow companion surfaces:

- `POST /api/private-retrieval/autocomplete` returns only current authorized
  labels and content-free source references, never snippets;
- `POST /api/private-retrieval/count` returns only a bounded visible count,
  its explicit 200-row ceiling and a conservative capped flag; and
- `POST /api/private-retrieval/search/stream` emits no-store NDJSON and opens a
  fresh database session to reauthorize the exact actor, capability, active
  generation, ACL/tombstone epochs and canonical source before every row.

If a stream fence changes, delivery terminates instead of skipping the failed
row and continuing. A revoke before the first row produces zero bytes; a revoke
after one authorized row prevents every later row. Autocomplete and count cross
the same final fence, so a stale prefilter result cannot disclose a revoked
title, snippet, source reference or match count.

Workspace Assistant resolves the requested tenant/client/Matter/IP docket or
document scope in the existing session owner and delegates private retrieval to
the same service. The service:

1. selects only the current active tenant generation and non-tombstoned,
   internal, non-privileged, active/approved projections;
2. applies canonical visible-Matter, visible-IP-docket, client, ethical-wall,
   source-type, typed-scope, source-reference, and exact policy-version checks
   in SQL;
3. caps candidates at 200 before lexical/vector ranking; and
4. reloads current membership/capability, active generation, record/document
   access, lifecycle/source eligibility, source version and document policy at
   hydration and immediately before delivery.

A candidate failing hydration disappears without a label, snippet, score,
count, or citation. Candidate caches hold identifiers only and partition by
company, membership, capability, generation, access epoch, tombstone epoch,
query hash, source type, filters, and locale. Cache hits cross the same current
hydration authorization boundary.

Workspace Assistant scope autocomplete also performs one final bounded actor,
tenant-policy, ACL, lifecycle, document-policy and exact resource-version pass.
Initial search rows are never serialized directly. The final pass uses the
fresh membership role rather than the request-start role and keeps document
policy work bounded without N+1 queries.

## Projection and provider workflow

The one-tenant rebuild operation reads current active Clients, Matters, indexed
Matter attachment chunks, active IP dockets, and current internally eligible
indexed IP documents. Public legal-authority content is absent by construction.
It is bounded to 2,000 projections, 4,000 characters per provider item, and 32
items per provider batch.

External embedding use must be explicitly enabled by the service caller after
tenant/provider policy has been satisfied. The provider receives only the
already-approved bounded source text. Tenant IDs, record IDs, labels, ACLs,
scopes, projection metadata, and payloads from another tenant are never placed
in a provider batch. Local mock and `fastembed` providers remain available for
offline verification.

The rebuild publishes only an empty non-readable building generation before
provider I/O and holds no tenant or generation database lock while waiting for
the provider. Every later projection write and verification presents the exact
access-policy and tombstone generations captured with the source snapshot. An
access, purge, or provider-deletion event landing during provider I/O therefore
fails the stale shadow instead of deadlocking the event or resurrecting content.
Generation activation and event enqueue serialize on the stable tenant row and
refresh locked generation state before making their decision.

Rebuild writes a shadow generation, verifies its live projection count and
ordered content-hash manifest, and may atomically activate it against the
expected current generation. Generation activation retains the IPLF-066A
epoch and unresolved-event fences. A rebuild cannot start while a pending or
failed event exists. It honors the latest applied revocation/tombstone ledger,
including a tenant-wide disposition tombstone, so retained canonical source or
backup state cannot resurrect private content. Unchanged source hashes reuse
the active generation's locally stored embedding instead of retransmitting the
same text to a provider.

Projection events are claimed in bounded, tenant-specific, skip-locked batches.
Each event has at most three attempts with 30-second then 60-second application
backoff. A failed attempt rolls back inside its savepoint without discarding
other events in the batch; terminal failures retain only the safe exception
class code. The maintenance selector uses indexed event/generation state, caps
each run at 50 tenants and reports truncation rather than scanning silently.

## Revocation, saved output, and user behavior

Canonical access, source, document, and lifecycle owners continue to emit the
IPLF-066A idempotent projection events. Event application neutralizes affected
content and embeddings across active and shadow generations, advances the
tenant security epoch, invalidates candidate caches, and locks or marks affected
saved Assistant output manifests for reauthorization.

Workspace Assistant read and export paths reauthorize saved manifests before
rendering. After revocation, an existing answer is replaced by the permission-
changed placeholder, citations are removed, and a repeated question abstains.
The dated Playwright regression proves this behavior after a full page reload
and at a 360-pixel viewport. It also proves that malicious instructions inside
an indexed source are treated as untrusted content by the deterministic local
provider.

Intelligent review freezes the exact private target projection ID, source
version/hash, active generation ID, access-policy generation and tombstone
generation beside its public-authority manifest whenever a private generation
exists. The worker checks that snapshot before and after provider I/O. Review
reads, selection/finalization/publication, Draft/report reads and DOCX/PDF/IP
bundle exports reauthorize the current tenant, target ACL, source version,
projection and exact security epochs. Publication copies the private entry into
the canonical `DraftVersion.source_manifest_json`; it cannot silently drop the
private provenance. A revoked or stale generation hides the review from lists,
omits the report from Draft lists and rejects direct reads/exports until a new
review is generated. Tenants without a private generation remain on the
existing default-off path.

`POST /api/workspace-assistant/sessions/{session_id}/citations/{citation_id}/open`
records a successful open only after the creator-private session, saved answer,
citation and current canonical source all reauthorize. The tenant-admin
`GET /api/admin/ai-outcomes` endpoint derives AI-GUIDE-12 outcomes from existing
Assistant turns/citations/action previews, canonical tasks, feedback items and
append-only audit events. It returns only tenant aggregates for task completion,
abstention, successful citation open, permission denial, proposed-action
confirmation and reported-answer rate. It exposes no company/member/record IDs,
content or employee dimension; permission denial is a count with no fabricated
denominator or rate.

Client-portal reports continue to use a closed client-safe field allowlist and
never read private projection text. Document publications recheck their
canonical document, current version, privilege, confidentiality, shareable
state, tenant, docket version and grant on list, open and download; an old
publication is reduced to `review_required` with no document metadata after a
canonical source restriction. A tombstone event blanks private text and
embeddings and locks copied Assistant output before a stale worker can write.

## Approved private-index disposition

The IPLF-071-owned `data_disposition` adapter is deliberately limited to
`private_index_projections`. It is not an execution route and cannot approve an
operation. Its caller must present a separately approved execute row that
exactly matches the immutable completed dry-run manifest and the server-derived
tenant target hash.

Under the execute-row lock, the adapter rechecks the current active retention
policy for a retention purge, resolves current legal-hold scope again, and
rejects held, blocked, ambiguous or invented targets. It emits the canonical
tenant tombstone event, verifies every projection is tombstoned with blank text
and no embedding, then stores content-minimized terminal evidence. Local index
cleanup receives a durable receipt. An external embedding provider without a
per-request deletion endpoint receives an explicit
`provider_deletion_contract_delay` exception and optional expected-resolution
date; absence of a provider receipt never means deletion. Terminal checkpoint
rows cannot exist without the private event, evidence payload/hash, attempt and
completion timestamp. Rebuild continues to honor that event after reload.

## Integrity and release boundary

`GET /api/private-retrieval/integrity` and the company-scoped command-line
operation return tenant-safe aggregates for active-generation manifest match,
live/tombstoned projections, pending/failed event lag, orphan or stale scopes,
stale/ineligible sources, unsafe tombstone payload, and the persisted age of a
repairable blocker. Direct integrity mode reports any mismatch as blocked.
`caseops-private-projection-maintenance` runs the bounded maintain mode every five
minutes. It processes due events, performs only bounded shadow repairs, and fails
the run if event or repair lag exceeded 300 seconds even when the same run
recovers it. Cloud Scheduler delivery has bounded retry/backoff, and a log-based
alert routes every structured `ERROR` run to the production alert channel with
correlation ID and runbook context.

Rebuilds serialize on a tenant-scoped PostgreSQL advisory lease held on a dedicated
connection across bounded commits. This prevents maintenance, release bootstrap,
and an operator rebuild from opening competing shadows without retaining Company,
Matter, or IP-docket row locks. A second rebuild owner waits at most 45 seconds.
If a canonical source or access mutation advances the security epoch, an event
arrives after the first drain, or another valid rebuild changes the active
generation, the worker deletes any failed shadow's partial rows, rolls back,
drains due events, re-inspects the tenant, and replans once. The retry still uses
bounded 50-row commits and must pass the same epoch and activation fences. Each
fresh-shadow batch performs one generation lock/epoch check, one bulk projection
flush and one bulk scope flush; it does not repeat generation reads, projection
existence reads, scope deletes, flushes or cache invalidations per row. The real
PostgreSQL acceptance creates 10,000 projections below an 850-statement and
60-second ceiling, then advances the epoch concurrently and proves the next batch
fails closed, removes the partial shadow and leaves the active generation intact.
A second typed epoch conflict deletes the new partial shadow and may defer the
repair to the next five-minute cadence only when an active fail-closed generation
remains, all blockers are repairable, and the persisted repair age is still within
the 300-second SLO. The structured result records the deferral reason and repair
age. The next run must replan and converge; an SLO breach, lease timeout,
non-repairable blocker, or unknown exception remains a tenant-isolated
release-blocking error. Cloud Run task retries stay disabled. PostgreSQL and
SQLite regressions force both attempts to lose their epochs, prove both shadows
are cleaned, then prove the following maintenance run activates a clean
generation.

The production verifier owns a SHA-scoped synthetic Matter/document fixture in
the isolated `caseops-ip-qa` tenant. The migration-first deploy repins that job
without execution before traffic, proves exact latest-only API/web identity and
health, then executes the current Cloud Run Job generation once. A successful
same-generation deploy retry skips execution; a failed execution remains failed
closed and cannot be retried automatically. The hosted browser verifies the
exact API/web SHA, finds that fixture through the public API and UI, answers
from its private projection, disposes the Matter through the canonical
lifecycle endpoint, then proves the saved answer/citation and direct private
search are revoked after reload. The bootstrap refuses to resurrect a terminal
same-release fixture.

The reciprocal purge/provider and durable-worker implementation is complete in
the repository. Exact corrective CI/Security/CodeQL, merge to `main`,
migration-first deployment, scheduler/alert inspection, immutable revision
identity and the production browser result remain release blockers. No local
result is production evidence.

## Rollback

Disable the entitlement/rollout consumer first. Keep the last verified active
generation and retained event/saved-output evidence, repair or replay bounded
events, rebuild a new shadow, verify the integrity aggregates, and activate
only with the expected-generation token. After evidence exists, restore-forward
is required; deleting the private tables or re-enabling the legacy document
fallback is not an acceptable rollback. The exact pause, triage, recovery,
provider-exception and alert-close procedure is in
`docs/runbooks/private-projection-maintenance.md`.
