# Retained recommendations and hearing packs — backend candidate

This additive GET-only surface reads stored Matter recommendations and existing
JSON hearing packs. It does not generate, decide, review, approve, finalize,
export, contact a provider or claim that stored citations are legally accurate.
The existing web APIs and their payload shapes remain available. Their latest
selection/order now breaks timestamp ties by the stored ID before any LIMIT.

The source branch starts at the closed queue checkpoint
`7495ee4808a6b1fc93f2e9a749102787b4f101f3`, merged with image-source repair
`42324f83b269eb7ec0f604a4b0d6e0c54df7802d` as
`be0eccf425e06c6698b523a90da8ce332409a6d3`. The earlier counsel checkpoint
`4970969374c57692f945bd221417922a4d1156c4` remains on its retained branch.
This does not incorporate later uncommitted compatibility, journal or counsel
repairs from other worktrees.

## HTTP contract

All paths start with `/api/matter-readthrough/{matter_id}`:

- `/recommendations`: metadata only, `created_at DESC, id DESC`.
- `/recommendations/{id}`: exact stored recommendation detail.
- `/recommendations/{id}/options`: `rank ASC, id ASC`.
- `/recommendations/{id}/decisions`: `created_at DESC, id DESC`.
- `/hearings/{id}/pack`: the exact hearing's latest JSON pack or JSON `null`,
  `generated_at DESC, id DESC`. A missing/foreign hearing is 404, not null.
- `/hearing-packs/{id}`: exact stored pack detail.
- `/hearing-packs/{id}/items`: `rank ASC, id ASC`.

Pages return `scope`, `kind`, `parent_id`, `order`, `limit`, `items` and
`next_cursor`. Limit defaults to 25, maximum 25; SQL reads at most 26 candidates.
Scope echoes the actual company ID, Matter status, active flag and lifecycle version.
Authorized retained closed Matter records remain readable, matching canonical
read behavior. They do not become operational or editable.

Each item retains its exact stored ID and actual ordering/timestamp fields.
`read_state` is `available`, `unsupported_size` or `unsupported_legacy`;
`record` is a typed payload or null. Unsupported content does not erase its
identity or hide valid siblings. No source value is truncated and represented
as complete. Nullable stored references, actors, next action and reviewed time
remain nullable. No record revision is invented: recommendations expose their
real `updated_at`; packs have no equivalent revision field.

A `source_ref` or stored citation is opaque recorded text. It is never resolved
or treated as permission to open another source/URL. Catalogue matching in an
older generator is not a guarantee of legal proposition accuracy.

## Bounds and current authority

Every serving statement includes the current tenant, active User/Membership/
Company and equality with the role used to compose the canonical Matter ACL.
The existing wall, restricted-access, current team and grant policy uses the
reviewed execution-time UTC expression. Final current-authority checks reject
lost visibility; a disappeared child parent cannot turn into a positive empty
collection. No permission or role grant is introduced.

SQL reads at most prefix+1 codepoints for each Text value (16,384 maximum),
with the declared smaller Varchar extents for metadata. UTF-8 encoding and JSON
escaping can increase byte size: therefore a complete child row is also bounded
to 32 KiB, a single detail to 256 KiB and a page to 1 MiB. Oversized or malformed
retained content is explicitly unavailable on this surface; writes and stored
bytes remain unrestricted by these read limits. Strict JSON and existing typed
strategy/analysis DTO validation prevent malformed cached content from looking
like a complete valid record.
The same scalar query also reads each original UTF-8 byte extent. A short
SQLite prefix that stopped at a retained NUL is explicitly unsupported rather
than being presented as the full source; nullable fields retain this check.

Continuations use HKDF-SHA256 and AES-GCM, domain-separated from the existing
backend secret with fixed versioned salt/info and authenticated audience.
There is no new secret or provider. The token binds actor/User/tenant/current
role, endpoint kind, exact Matter and child parent, limit, actual lifecycle
version, source ID/sort key, issuance and one-hour expiry. It is opaque and is
not an access grant. Every page reauthorizes live data. Invalid scope/signature/
expiry is 400; a valid continuation whose lifecycle/anchor changed is 409 and
requires an explicit first-page reload. No automatic mutation or cursor replay
is introduced. Cursor tests control only the cursor-local clock, never JWT time.

These pages are current reads, not a frozen snapshot: valid inserts/updates
between requests may change subsequent membership. An unchanged recommendation
`updated_at` cannot certify changes to independently mutable option rows. Anchor
checks never claim otherwise.

## Schema and acceptance boundary

Migration `20261027_0007` follows `20261027_0006` and adds five nonunique support
indexes only. Recommendation metadata uses the same `intelligent_review`
exclusion as the legacy Matter recommendation read, with its exact partial
predicate. The serving predicate is a fixed typed SQL literal so a prepared
query does not replace that reviewed constant with an unknown generic-plan
parameter. There are no new tables, columns, triggers, write constraints,
permissions or history rewrites. Valid old-column writes, wide Text and stored
outbox/audit/receipt bytes must survive migration and restart unchanged.

Index declarations do not prove a 400-work bound. Prepared tests retain full
all-node default/adverse plans, including filters, loops, rechecks, bitmap
children and intermediate nodes, with indexes installed before and after
seeding and both source cohort insertion orders. The 400 cap and SQL deadlines
are unchanged. Whole SQLite/PostgreSQL HTTP, migration and policy journeys,
canonical map/projection, actual changed-migration preflight against current
main, generated OpenAPI integration and native UI acceptance are required
separately. This document and source preparation do not mark those gates passed.
