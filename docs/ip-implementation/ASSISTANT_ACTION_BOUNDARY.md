# Assistant proposed-action boundary

## Scope and ownership

IPLF-064 extends Ask this Workspace with an explicit preview and confirmation
boundary for proposed tasks, drafts, and allowlisted Matter metadata changes.
Navigation and verified-source search remain read-only links. The assistant
does not create an alternate task, Draft, Matter, IP, access-control, model-run,
billing, or audit writer.

`assistant_action_previews` owns only the retained handoff evidence: actor,
tenant, session and turn, proposal, action and target identity/version, exact
canonical payload hash, policy/session versions, token hash, expiry, status,
confirmation time, and canonical result link. Canonical domain services remain
the sole mutation owners:

- Matter tasks use `create_matter_task`;
- IP tasks use `create_ip_shared_task` against the resolved docket;
- Matter Drafts use `create_draft`;
- trademark pleadings use `create_ip_draft` against an explicit proceeding and
  one server-reviewed compatible template;
- allowlisted Matter metadata uses `update_matter` with its optimistic token.

The canonical services accept a transaction-owner option so the domain write,
domain audit, assistant confirmation, result link, session-version increment,
and assistant audit commit atomically. Existing routes retain their prior
commit behavior.

## Preview contract

Only a write proposal retained on the named assistant turn can be previewed.
The server rechecks the active actor and action-specific capability, tenant AI
policy, creator-private active session/version, current target access, and the
target version captured by the proposal. The browser supplies ordinary user
input; it never supplies tenant identity, actor identity, owner identity,
target identity/version, policy version, session version, or an IP template
catalog.

Preview performs no domain mutation. It persists a 15-minute evidence row and
returns the target label, exact before/after values, required capabilities,
warnings, expiry, and an HMAC confirmation token. A new preview for the same
proposal and actor supersedes prior pending previews. The token binds every
security-relevant identifier, the canonical payload hash, session and policy
versions, actor, target version, and expiry.

## Confirmation contract

Confirmation accepts only the preview ID, original assistant-session version,
and exact server-issued token. Under one transaction and stable lock order it
rechecks:

1. current active actor and every action-specific capability;
2. current tenant AI policy version and assistant enablement;
3. creator-private active session and optimistic version;
4. pending status, actor ownership, token hash/signature, and expiry;
5. original retained proposal and its write availability;
6. current target access, tenant, type, identity, and optimistic version;
7. server-owned IP docket/proceeding/template compatibility when applicable.

Any mismatch fails closed without a domain write. Confirmed replay is
idempotent and returns the original result; it does not create a second task or
Draft. Successful confirmation increments the assistant session version and
supersedes other pending previews for that session so a browser must continue
from current server state.

## Supported writes

- Task: Matter, IP docket, IP asset, trademark application, or IP proceeding;
  IP child targets resolve their canonical docket server-side.
- Draft: Matter, or an explicit IP proceeding. IP Drafts remain unapproved,
  review-required, and incapable of automatic filing.
- Matter field update: title, description, matter type, client name, opposing
  party/counsel, practice area, court name, or judge name.

Lifecycle, active state, matter code, case/filing/CNR identifiers,
responsibility, team/access state, court catalog identity, hearing dates,
financial values, and every other field are excluded. The assistant cannot
dispose, reopen, activate, approve, file, serve, submit, notify, or schedule a
hearing through this boundary.

## Data, retention, and rollback

Migration `20260829_0001` is additive and creates one indexed tenant-scoped
table. Composite foreign-key prefixes are indexed in database column order,
in addition to bounded actor/status/expiry and session/turn/proposal lookup
indexes. No backfill, provider call, worker, scheduler, or autonomous executor
is introduced.

Preview/confirmation evidence follows the assistant legal-work-product and
litigation-hold boundary. Automated disposition remains unauthorized until
the approved shared disposition owner exists. Downgrade therefore refuses to
drop retained rows; rollback is restore-forward after application rollback.

## Verification boundary

Automated proof covers migration round-trip and index coverage, no write on
proposal or preview, exact task/Draft/field changes, Matter and trademark IP
targets, token tampering, supersession, expiry, tenant isolation, actor
capability changes, session/policy/target staleness, idempotent replay,
transaction rollback, responsive dialog behavior, and generated OpenAPI drift.
Production completion additionally requires exact API/web identity,
migration-first deployment, database index health, one post-route QA bootstrap,
and dated UJ-23 normal and proposed-write exception acceptance.

IPLF-065 retains prompt-injection, prohibited-output, legal-safety, and feedback
evaluation ownership. IPLF-066 retains private retrieval and action analytics.
Neither is claimed by IPLF-064.
