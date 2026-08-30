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
   hydration.

A candidate failing hydration disappears without a label, snippet, score,
count, or citation. Candidate caches hold identifiers only and partition by
company, membership, capability, generation, access epoch, tombstone epoch,
query hash, source type, filters, and locale. Cache hits cross the same current
hydration authorization boundary.

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

Rebuild writes a shadow generation, verifies its live projection count and
ordered content-hash manifest, and may atomically activate it against the
expected current generation. Generation activation retains the IPLF-066A
epoch and unresolved-event fences. Projection events are claimed in bounded,
tenant-specific, skip-locked batches; stored failures contain a safe exception
class code rather than raw source/provider error text.

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

## Integrity and release boundary

`GET /api/private-retrieval/integrity` and the company-scoped command-line
operation return tenant-safe aggregates for active-generation manifest match,
live/tombstoned projections, pending/failed event lag, orphan or stale scopes,
stale/ineligible sources, and unsafe tombstone payload. Any mismatch blocks
release. The CLI also provides bounded event processing and rebuild operations;
it is an operational entry point, not a second workflow owner.

The repository-local slice remains incomplete until the unimplemented
reciprocal scope is added and the exact integrated release is verified. In
particular, private intelligent-review/report saved-output registration,
privacy-bounded AI-GUIDE-12 analytics, portal/internal and export-after-purge
adversarial coverage, provider deletion outcomes, durable production worker
scheduling, hosted CI/Security/CodeQL, deployment, and dated production proof
remain release blockers. No local result is production evidence.

## Rollback

Disable the entitlement/rollout consumer first. Keep the last verified active
generation and retained event/saved-output evidence, repair or replay bounded
events, rebuild a new shadow, verify the integrity aggregates, and activate
only with the expected-generation token. After evidence exists, restore-forward
is required; deleting the private tables or re-enabling the legacy document
fallback is not an acceptable rollback.
