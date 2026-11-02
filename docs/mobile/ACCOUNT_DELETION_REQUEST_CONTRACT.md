# Self account-deletion request intake

This slice records a signed-in person's request. It does not delete an account,
deactivate access, purge a Matter, schedule work, send email, or claim fulfillment
or store-policy compliance. Manual support email remains a separate enquiry.

The subject is the authenticated global `User.id`. The requesting company and
membership are server-derived routing/audit provenance. They are not the scope
of deletion authority and are never returned in a receipt. A person with valid
memberships in two workspaces sees the same own request. Another person, even an
owner or administrator in the originating workspace, cannot read it. Portal,
report-console and unauthenticated identities receive no tenant self authority.
A founder's ordinary valid tenant session acts only for that same tenant User;
founder or report privileges do not grant access to anyone else's request.

`POST /api/account/deletion-requests` accepts exactly:

```json
{"operation_id":"<canonical nonzero UUID>","confirmation":"request_account_deletion"}
```

It returns HTTP 202 with `id`, `operation_id`, `request_type:account_deletion`,
`status:received`, an explicit UTC `requested_at`, and `deletion_completed:false`.
An exact operation replay returns the same receipt without changing request or
audit bytes. A different operation while that request remains received returns
409 `account_deletion_request_pending`; it does not make another request or
rotate its identity. One open request exists per global User, across workspaces.
Only `received` is supported; future fulfillment requires an explicit reviewed
protocol and migration rather than changing this constraint silently.

`GET /api/account/deletion-requests` returns `{"request":null}` or the own
receipt. `GET /api/account/deletion-requests/{request_id}` returns only the own
receipt or 404. All successful responses are non-cacheable. There is no list of
other users, administrator review, status-update or completion endpoint.

Every request uses the existing tenant authentication realm, cookie precedence,
CSRF and MFA rules. Receipt intake rechecks current company/membership/User and
token cutoffs under the canonical Company → Membership → User identity fence.
Native families are additionally rechecked under their device lock for current
revocation, expiry and MFA. SQLite uses its canonical absent-row writer lock;
database uniqueness and conflict admission retain one request and one audit
under overlapping same-operation submissions. There is no transport retry.

The winning insert and its audit commit together. The audit uses the existing
private global user/security audit table, with server-derived actor IDs, no
company or platform-admin principal, and fixed request/status metadata. It does
not copy a name or email and is not a tenant `AuditEvent`. The originating
workspace's ordinary owner audit export therefore cannot disclose the request.
An exact replay adds no audit. A response failure after commit does not undo
the request: the subject must reconcile the persisted own receipt before an
explicit retry.

A native client should explain that requesting is different from deletion,
require explicit confirmation, retain one operation UUID for one attempt, and
submit once. After an unknown acknowledgement it should reload its own receipt
before offering another attempt. A conflicting request should show that receipt.
It must never show a completed/deleted state from this contract. No passwords,
TOTP codes, legal documents, freeform reason or copied contact details are request
fields. No freeform personal data is added to the durable receipt.

Operator fulfillment, identity-verification requirements, retention exceptions,
cross-workspace ownership, provider-held data, completion notices, public web
intake and promised completion periods remain outside this slice. They need an
approved operational policy and real execution evidence before any completion
claim. This request record does not authorize bypassing existing legal holds or
the non-executable tenant data-governance boundary. The additive migration refuses
all downgrades before DDL, preserving retained rows, columns, indexes and revision.

Offline regressions use normal synthetic HTTP sessions and the no-paid marker,
with external HTTP transports denied. They prove request persistence and replay,
not actual deletion, email delivery or mobile UI acceptance. PostgreSQL and native
artifact acceptance remain separate until their complete intended gates run.

2026-10-27 source review correction: the original intake implementation wrote
an exportable tenant audit event, contradicting the private self-request scope.
That original 15-file candidate and its 75 passing common/role test results are
retained as earlier scope; those tests did not exercise tenant audit export.
The replacement routes this event to the existing private global audit primitive
and adds real owner-export and post-commit reconciliation regressions. Their
SQLite/PostgreSQL execution remains pending the assigned test resource window;
this dated correction is source preparation, not a new acceptance result.
