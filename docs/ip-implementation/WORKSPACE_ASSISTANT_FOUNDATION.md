# Workspace Assistant foundation

## Scope and canonical owners

IPLF-062 extends existing tenant AI policy, `ModelRun`, billing, audit,
Matter/client/IP record, document, access-control, and source owners. It adds
only the conversation records needed for permission-scoped Ask this Workspace:

- `assistant_sessions` owns creator-private lifecycle, policy snapshot,
  optimistic version, and retention expiry;
- `assistant_session_scopes` owns explicit ordered references to permitted
  records and documents, not copied business records;
- `assistant_turns` owns bounded user/assistant content, content hashes,
  retrieval and permission snapshots, status, and `ModelRun` linkage;
- `assistant_citations` owns exact record/document/source version provenance.
- `assistant_action_previews` owns the retained, expiring, actor-bound preview
  and confirmation evidence added by IPLF-064, not the resulting domain record.

The assistant does not create a second Matter, client, IP, document, research,
task, draft, billing, access, or legal-source owner. Migration
`20260827_0002` is additive and refuses downgrade while retained assistant
evidence exists.

## Permission and retrieval boundary

Sessions are private to the creating active membership. Scope search and scope
admission resolve tenant identity from the authenticated context and apply the
canonical access services. Supported scope types are tenant, client, Matter,
IP docket, IP asset, trademark application, IP proceeding, Matter document,
and IP document.

Every ask reauthorizes the full explicit scope before retrieval. Retrieval is
bounded to 24 scope references and 20 sources, batches document access checks,
and does not perform a corpus-scale scan or per-row access query. After the
provider returns, the service refreshes authentication, policy, session
version, lifecycle, and source access before any answer, citation, `ModelRun`,
or billing write is committed. Revoked or changed sources are omitted from
subsequent turn hydration and citation rendering.

## Answer and provider boundary

Workspace facts require exact citations to the authorized record/document
version. A legal proposition requires permitted verified legal evidence; when
that evidence is absent, the service deterministically abstains and offers a
verified-source search. An answer without an admissible citation is not
persisted as an answered result.

Assistant provider calls use the dedicated `assistant` purpose, tenant model
allowlist, bounded prompt/source text, a 60-second deadline, and at most one
retry. The database session is released before the network call, then all
authority is rechecked. Provider construction, timeout, quota, invalid output,
and runtime failures share one typed, redacted, audited failure boundary. No
model or tokenizer is downloaded or initialized on the interactive path.

## Actions and retention

The assistant may return navigation, search, draft, task, or field-change
proposals. IPLF-062 itself performs no proposed write. IPLF-064 enables a
separate 15-minute preview/confirm boundary for compatible Matter and IP
targets; preview never mutates, and confirmation reauthorizes actor, policy,
session, proposal, target access/version, token, and canonical input before
delegating atomically to the existing task, Draft, or Matter writer. The exact
contract and excluded fields are maintained in
`ASSISTANT_ACTION_BOUNDARY.md`.

Tenant policy controls enablement, allowed assistant models, and retention from
1 to 3,650 days under optimistic concurrency. Users can list, inspect, archive,
change explicit scope, page turns, and export a bounded versioned conversation.
Destructive deletion is intentionally fail-closed: until IPLF-071 supplies an
approved legal-hold-aware disposition path, `DELETE` records a denied audit and
returns `assistant_deletion_governance_required` without deleting evidence.

## Governed feedback boundary

IPLF-065 lets the session creator rate or report an assistant answer. The
feedback target is the existing canonical assistant turn and session; no prompt,
answer, citation, source text, retrieval payload, or model output is copied into
the feedback table or feedback audit metadata. Submission reauthorizes the
creator-private session and tenant before accepting the reference, and a
cross-tenant, cross-session, user-turn, or invented target fails closed.

The same tenant-admin review queue used for Product Guide feedback owns status,
priority, reviewer, and bounded review notes. This is operational feedback, not
an autonomous prompt update, model-training corpus, analytics writer, worker,
or scheduler. Resolved and dismissed records remain terminal.

## Bounds and operational behavior

- 24 scopes per session, 20 scope-search results, 20 retrieved sources;
- 1,600 source characters per prompt source and 5 citations per answer;
- 200 retained turns per session and 50 turns per page;
- 100 sessions per list page;
- creator-private session reads, exports, mutations, and archives;
- no assistant worker, scheduler, provider-side autonomous action, or hidden
  analytics writer.

The five assistant tables, tenant AI policy additions, and canonical-reference
feedback table are registered in the data-governance map. Assistant lifecycle,
answer, abstention, provider failure, export, archive, blocked deletion, action
preview, action confirmation, and feedback review events are registered in the
event catalog. Production activation remains gated by exact-release migration,
index-health, CI/security, and dated browser acceptance.
