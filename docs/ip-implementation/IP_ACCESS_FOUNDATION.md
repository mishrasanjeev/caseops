# IPLF-026A internal record-access foundation

## Bounded verdict

IPLF-026A extends the existing internal access and ethical-wall owners to IP
docket targets. It does not complete UJ-46 or claim the IP-ACCESS,
SEARCH-ACL, or SEC-GOV requirement families; those remain allocated to
IPLF-026B and later milestone slices.

No portal grant, access-review campaign, emergency-access session, support
break-glass state, client-policy row, or IP-only grant/wall table is created.

## Canonical ownership

| Concern | Canonical owner |
|---|---|
| Grant state | `MatterAccessGrant` / `matter_access_grants` |
| Ethical-wall state | `EthicalWall` / `ethical_walls` |
| Decision and reconciliation | `services/matter_access.py` |
| Tenant audit correlation | `AuditEvent.ip_docket_id` |
| IP document source reauthorization | `services/source_actions.py` delegates to the same docket decision |

The historical Matter table names remain compatibility names. The schema
accepts exactly one Matter-or-IP target and exactly one membership-or-team
subject with company-matching foreign keys. There is no `ip_access_grants`
or IP-only ethical-wall owner.

## Expand, backfill, switch

1. `20260811_0001` adds nullable tenant/IP/team/effective/revocation/version
   columns, target policy versions, and audit correlation while the previous
   Matter writer remains valid.
2. `20260811_0002` backfills tenant/effective facts and snapshots the
   effective policy of linked Matters into independent IP target rows.
   Explicit grants and walls are copied once. Restricted, assignee, owner, and
   team-scoped visibility is preserved without continuing inheritance.
3. `20260811_0003` drains the nullable old-writer tail, blocks unresolved or
   cross-company rows, adds exactly-one-target/subject checks, composite
   tenant foreign keys, effective-window/version checks, active uniqueness,
   audit/source constraints, and the team composite key.

Downgrade removes derived IP snapshot rows before restoring the legacy
Matter-only shape. Re-upgrade reconstructs the snapshot. The migration test
proves expand, backfill, a post-backfill legacy write, switch, downgrade, and
re-upgrade.

## Decision contract

The IP predicate is:

1. company and active authenticated membership are established by request
   context;
2. any effective membership/team wall denies;
3. an unrestricted IP docket is otherwise visible;
4. a restricted IP docket requires an effective membership/team grant;
5. expiry and revocation remove the row from the effective decision;
6. company owners do not bypass restricted IP policy;
7. linked Matter permissions are not consulted after cutover.

Matter routes retain their legacy owner bypass, assignee rule, restricted
grant behavior, ethical-wall precedence, and optional team scoping. They now
consume the same effective membership/team row shape.

## Protected surfaces

- Portfolio list and count apply `visible_ip_dockets_filter` before
  serialization.
- Direct docket, lifecycle, identifier search, task/deadline/hearing adapters,
  and child services delegate through `_docket_or_404`, which invokes the
  same IP decision.
- IP document list, detail, mutation, download, and processing paths
  reauthorize every linked docket.
- `ip_document_version` is a protected source target. Source-open resolves
  and reauthorizes the linked document/docket before returning an internal
  redirect.
- `/api/ip/dockets/{id}/audit` authorizes the docket before counting or
  returning correlated audit rows.
- Audit exports filter correlated IP audit rows through the requester's
  current docket predicate at worker execution time. Record-level IP events
  without a safe docket correlation are omitted fail-closed rather than
  treated as tenant-global events.

Denied direct reads return the tenant-isolation 404 and append a correlated
denial audit without revealing existence. Source opens are rechecked at open
time and use no client-side authorization.

## Release-blocking reconciliation

`/api/ip/access/reconciliation` is protected by the existing
`matter_access:manage` capability and reports:

- nullable legacy tails;
- invalid target or subject cardinality;
- target-company or subject-company mismatch;
- uncorrelated direct IP-docket audit rows.

`healthy=true` requires every count to be zero. The foundation contract
endpoint also publishes the canonical writer, supported targets/subjects,
Matter/IP owner-bypass distinction, forbidden parallel owners, and explicitly
excluded persistence.

## Deliberately deferred to IPLF-026B

- grant/revoke/preview UI and API workflow with optimistic concurrency,
  reason, affected-resource preview, self-lockout/four-eyes handling, and
  invalidation effects;
- the complete UJ-46 normal and exception paths;
- all allocated IP-ACCESS, SEARCH-ACL, and SEC-GOV acceptance evidence;
- portal, assistant/index/cache, queued-delivery, notification, autocomplete,
  report/export UX, and linked-record mismatch warnings beyond the foundation
  surfaces proved here;
- human legal/security/pilot acceptance.
