# IPLF-066A private-retrieval foundation

## Outcome and boundary

IPLF-066A adds the repository-controlled security boundary needed before a
tenant-private lexical/vector retrieval workflow can be exposed. It implements
the persistence and service contracts for PRD Section 13.26 without adding a
second public-authority corpus, a browser workflow, a provider call, or an
independent access-policy owner.

This is an additive, default-unused foundation. IPLF-066B retains the
user-facing retrieval/revocation journey, projection workers, provider-safe
embedding batches, aggregate integrity observability, adversarial browser
coverage, and exact-release proof. A locally green IPLF-066A branch is not a
deployed fix.

## Canonical ownership

| Concern | Canonical owner | IPLF-066A behavior |
| --- | --- | --- |
| Public authorities | Existing authority document/chunk/vector tables and services | Never copied into a private projection or candidate cache |
| Matter/IP visibility | `MatterAccessGrant`, `EthicalWall`, active membership, Matter lifecycle and IP docket lifecycle | Reused in the SQL candidate predicate and hydration; no parallel grant or wall table |
| IP document disclosure | Existing IP document metadata, current version and `get_ip_document_policies` | Current document policy is rechecked at hydration |
| Assistant answer provenance | Existing `AssistantTurn` and `AssistantCitation` | Adds a content-free source/version access manifest; copied answer text remains with the existing turn owner |
| Private projection state | `PrivateIndexGeneration`, `PrivateIndexProjection`, typed `PrivateIndexProjectionScope`, and `PrivateProjectionEvent` | New tenant-private derived-data owner |

## Persistence boundary

Migration `20260830_0002` creates five empty additive tables. It does not scan,
copy, embed, or backfill existing client content.

- `private_index_generations` permits one active generation per company and
  records independent access-policy and tombstone epochs.
- `private_index_projections` stores the exact source/version, tenant, chunk,
  confidentiality/privilege, source/approval state, policy versions, embedding
  metadata, content hash, and durable tombstone state.
- `private_index_projection_scopes` stores one or more tenant-correlated typed
  client, Matter, or IP-docket scopes. Database constraints require exactly one
  typed target per row.
- `private_projection_events` is the idempotent access/source/lifecycle event
  ledger and records affected projection and saved-output counts.
- `private_saved_output_access` stores only answer/source/version/hash and
  security-generation references. It does not duplicate answer or source text.

PostgreSQL receives a partial trigram index for live private content. Tenant,
generation, tombstone, source and typed-scope indexes support the mandatory
prefilter. Foreign keys are tenant-correlated where a target is tenant-owned.
Downgrade refuses to discard retained projection, revocation, or saved-output
evidence; an empty installation remains reversible.

## Retrieval security boundary

Candidate selection and content exposure are deliberately separate:

1. The request context is refreshed from current active Company, User and
   Membership rows. The required server capability is recalculated; request
   context or frontend state is not trusted.
2. SQL limits candidates to the current active tenant generation, live and
   approved non-privileged/private-AI-eligible rows, canonical visible Matter
   or IP docket predicates, active clients, exact typed-scope policy versions,
   requested source types and a closed set of typed filters.
3. Candidate work is capped at 200 before ranking. Lexical matching stays
   inside the prefiltered SQL query. Semantic retrieval ranks only the bounded
   ACL-prefiltered candidate set.
4. Hydration reloads active membership/capability, canonical record/document
   access, source lifecycle/version/policy and active generation. A failed
   recheck drops the row without exposing its count, label, snippet, hash or
   score.

Unknown filters fail closed. A caller may select the operation-specific
capability, but `ai:generate` is the default security partition. The eventual
IPLF-066B routes must independently enforce current feature entitlement and
rollout before invoking this service.

## Cache contract

The process cache stores only bounded projection identifiers. Its key includes
company, membership, required capability, active generation, access epoch,
tombstone epoch, query hash, source types, typed filters and normalized locale.
Raw query or content is not present in the key or value. Every hit crosses the
same hydration reauthorization boundary as a miss. Access/source/lifecycle
events and generation activation invalidate every entry for the affected
tenant.

## Revocation, lifecycle and shadow generations

The canonical Matter/IP access mutators now increment the canonical record
policy version and apply an idempotent private projection event in the same
database transaction. Matter and IP lifecycle transitions, and material IP
document version/state/link/metadata changes, do the same. Event application:

- increments the appropriate active security epoch;
- neutralizes every affected live projection in active and shadow generations
  by blanking content and removing the embedding before setting the tombstone;
- marks affected saved outputs for reauthorization or locks them for source,
  revocation and lifecycle changes;
- invalidates the tenant candidate cache; and
- resets a ready shadow generation to building if its verification manifest
  became stale.

A shadow can become ready only after its expected live projection count and
ordered content-hash manifest match. Activation locks the tenant generations,
rejects stale epochs and unresolved events, retires the current generation,
and then atomically activates the verified shadow. A failed/stale rebuild
therefore cannot replace the last good generation or resurrect a tombstoned
row.

## Saved-output behavior

Workspace Assistant persistence records one content-free access row for every
cited source/version on an assistant answer. Read and export serialization
re-resolves current source access/version and combines that result with the
saved-output lock. If either check fails, the existing answer surface returns
its `permission_changed` placeholder with no citations or copied answer text.

IPLF-066B must reuse this owner when integrating private intelligent-review and
report outputs. It must not create a separate saved-answer ACL registry.

## Regression contract

The IPLF-066A suite proves:

- cross-tenant known-ID and candidate-count attempts expose nothing;
- SQL filters and canonical restricted-record grants are enforced before rank;
- a role/capability downgrade is caught during hydration;
- a cached or preselected candidate is blocked after revoke;
- tombstones blank private text and embeddings in current and shadow
  generations;
- duplicate projection events are idempotent;
- a verified shadow cannot resurrect a revoked row;
- saved Assistant answers lock and render without copied text/citations; and
- every security/cache-key dimension changes the cache partition without
  storing the raw query.

The data-governance registry classifies the SQL content and derived embeddings,
registers the identifier-only cache, and includes all five tenant tables in the
purge propagation inventory. This does not activate automated retention,
purge, provider deletion or release.

## Rollback and remaining release gates

Before any private content is written, rollback is an ordinary downgrade to
`20260830_0001`. After retained evidence exists, restore-forward is mandatory:
disable the consuming IPLF-066B surface, keep the last good generation, repair
or replay projection events, verify hashes/scopes/epochs, and activate only a
new verified shadow. Never delete the evidence tables to make a rollback pass.

Production activation remains blocked on the IPLF-066B worker/route contract,
real-PostgreSQL query-plan and scale proof, provider-minimization proof,
aggregate integrity/lag gates, adversarial Playwright coverage, exact-main CI,
migration-first deployment, and dated exact-revision production verification.
