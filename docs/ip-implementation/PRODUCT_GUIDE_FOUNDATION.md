# Product Guide foundation

## Scope and ownership

IPLF-061A extends the existing public `/guide` owner. It does not create a
second help page, assistant corpus, workspace-search index, action writer,
feedback queue, analytics store, model run, worker, or scheduler.

The single maintained catalog is
`docs/ip-implementation/PRODUCT_GUIDE_CATALOG.json`. It contains the approved
English (India) guide section index and the navigation-command catalog. The
existing `/guide` JSX remains the detailed long-form content owner. The catalog
must name every rendered section in the same order, so an index can neither
omit content nor invent content that the guide does not render.

The API and web production images have separate Docker build contexts and
cannot read `docs/`. `scripts/product_guide_catalog.py render` therefore emits
byte-identical, generated JSON into both runtime contexts:

- `apps/api/src/caseops_api/product_guide/catalog.generated.json`
- `apps/web/lib/product-guide.generated.json`

`scripts/product_guide_catalog.py validate` is a required CI gate. It rejects
projection drift, malformed versions, duplicate IDs or routes, unknown
capabilities, dead Next.js routes, guide-section mismatch, excessive catalog
size, and any reintroduction of manually maintained Sidebar or guide indexes.

## Runtime contract

`GET /api/product-guide/catalog` is public and read-only. It returns version,
language, fingerprint, canonical path, update date, and the ordered guide
sections. It deliberately does not publish the command catalog.

`GET /api/product-guide/search` requires the current tenant session. It accepts
`q`, bounded `limit` (1-10), and optional `client_version`. It returns:

- `matched` with approved guide anchors and permitted navigation commands;
- `permission_required` with only the missing capability and a generic access
  explanation, never a restricted record name or destination;
- `no_match` with deterministic suggested searches and no generated answer;
- `version_status: stale` when a caller presents an outdated catalog version.

Command visibility is resolved from
`resolve_membership_capabilities(session, membership)`. Fixed roles, active
custom roles, revocation, and platform-admin capabilities therefore use the
same server-owned permission decision as protected application routes. The
browser does not invent tenant IDs, role mappings, or capabilities.

Search is a deterministic, in-memory lexical ranking over 27 help sections and
44 navigation commands. It performs no SQL corpus scan, provider call, model or
tokenizer resolution, network access, write, or analytics emission. Query
length is capped at 160 characters, returned results at 10, sections at 64,
and commands at 96.

## Non-duplication boundaries

IPLF-061B owns UJ-22's product-guidance UI, approved help navigation,
permission explanation, stale-version handling, terminology, and deterministic
abstention. IPLF-062 owns assistant sessions, turns, citations,
permission-scoped workspace retrieval, retention, archive, export, and the
fail-closed deletion request. Destructive deletion remains unavailable until
the legal-hold-aware disposition owner is approved; a blocked request is
audited and returns a typed conflict rather than erasing retained evidence.
IPLF-064 owns preview/confirm write actions. IPLF-065 owns governed answer
feedback and safety evaluation. IPLF-066 owns private retrieval plus assistant
and action analytics. Existing source actions, ModelRun, AI policy, audit,
record access, Matter, client, IP, document, and search owners remain
authoritative.

The guide links to `/app/assistant`, but assistant questions and generated
answers never update the guide catalog. The guide remains reviewed source
content; assistant conversations are tenant-restricted legal content governed
by `WORKSPACE_ASSISTANT_FOUNDATION.md`.

The AI-GUIDE family is reciprocally allocated to those owners by behavior,
rather than mechanically claimed in full by IPLF-061B. IPLF-061A claims no
AI-GUIDE requirement or UJ-22 path completion; it provides only the bounded
technical dependency declared by the manifest. UJ-22 remains incomplete after
the 061B UI is delivered until its governed report/analytics postcondition is
implemented by the later assigned owners.

## Verification

Automated proof covers projection rejection cases, public catalog privacy,
ranking, stale clients, deterministic abstention, custom-role filtering,
sanitized denied commands, no audit writes, input and output bounds, runtime
latency, OpenAPI generation, Sidebar regression, TypeScript, and Playwright at
360px and 1280px. The dated production acceptance additionally gates exact API
and web release identity before checking the live catalog, search contract, and
responsive `/guide` page.

IPLF-061B adds component and production-build browser proof for direct
navigation, missing permission, stale content, abstention and suggested search,
signed-out/unavailable behavior, mixed permitted and denied matches, and the
360px layout. Its dated production spec is part of the canonical production
batch.

This slice has no schema or data backfill. Rollback is an application rollback
to the preceding exact release; there is no database downgrade or cleanup.
