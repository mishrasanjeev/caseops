# IP internal-access workflow

## Boundary

IPLF-026B adds the user-facing preview, confirm, grant, revoke, and ethical-wall
workflow to the canonical record-access owner introduced by IPLF-026A. It does
not create an IP-specific grant table or a second policy engine.

The canonical rows remain `MatterAccessGrant` and `EthicalWall`, with exactly
one Matter-or-IP target and one membership-or-team subject. Portal grants,
access-review campaigns, and emergency-access sessions remain outside this M2
workflow and are not inferred from a linked Matter.

## Authorization and policy

- All panel, preview, and apply routes require `matter_access:manage`.
- Apply requires the existing `record_access_change` step-up purpose whenever
  tenant policy or enrollment requires recent MFA.
- A wall is evaluated before a grant. A restricted docket requires an active
  membership or team grant; a default-visible docket remains hidden from an
  active membership or team wall.
- Effective and expiry timestamps are evaluated at access time. Revocation is
  soft and records the actor, time, reason, and incremented row version.
- Cross-company and inactive subjects fail closed. Duplicate active rows and
  stale policy versions are rejected.
- An actor cannot preview a change that removes their own last effective
  access; a different authorized owner or access administrator must perform it.

## Preview and commit

`GET /api/ip/dockets/{id}/access` returns current policy, policy version,
effective internal membership count, queued deliveries, and complete
grant/wall history. The explicit exclusions make the persistence boundary
visible to operators.

`POST /api/ip/dockets/{id}/access/preview` is read-only. It calculates
membership visibility before and after the proposed command, documents and
queued deliveries affected, linked-Matter mismatches, and a deterministic
server-secret HMAC covering company, docket, actor membership, expected policy
version, reason, subject, effective window, and action. The token cannot be
fabricated from request fields or transferred to another access manager.

`POST /api/ip/dockets/{id}/access/apply` locks the docket row and recalculates
the preview. The command is rejected unless both the optimistic policy version
and preview token still match. The grant/wall mutation, docket policy-version
increment, and correlated audit event commit together.

Audit metadata retains the reason, subject/row identifiers, old and new policy
versions, preview token, affected counts, invalidation operation identifier,
and the invariant that linked-Matter permissions were not copied.

## Discovery and delivery invalidation

The access-policy version is the generation fence for result hydration. Every
live list/count/direct/document/source/audit/export surface continues to use
the shared SQL policy predicate from IPLF-026A; no stale allow-list is copied
into this workflow.

Notification delivery reauthorizes an internal recipient against the IP docket
immediately before dispatch. A queued or retry-scheduled intent is blocked with
zero external calls after access is revoked. An IP portal recipient fails
closed because this epic does not generalize the existing Matter portal-grant
owner.

## Linked Matter and portal boundary

Linked Matter visibility is displayed only as a mismatch warning. Granting or
revoking IP access never broadens or narrows the Matter, and Matter access does
not substitute for an IP grant.

The UI offers membership and team subjects only and states that portal grants,
access reviews, and emergency access are managed separately. The existing
Matter portal owner already removes a revoked grant from the next portal/me
read, denies later outside-counsel calls, and rejects sessions older than
sessions_valid_after. Full IP-target portal scope remains later reciprocal
work; this slice preserves those immediate-revocation semantics without adding
portal persistence.

## UI and responsive behavior

Authorized users see an Access workspace on the selected IP docket. Reason is
mandatory before preview. Policy toggles, membership/team grants, walls,
effective windows, history, subject-specific revoke controls, gains/losses,
document and queued-delivery counts, warnings, cancel, and confirm remain
visible and operable at 360 px. Controls are full-width and wrapping on mobile,
with explicitly shrinkable nested containers.

## Data and rollback

This slice has no schema migration. It consumes the target, subject, effective
window, revocation, audit-correlation, and policy-version fields delivered and
migrated by IPLF-026A.

Runtime rollback is therefore a code rollback: old readers continue to honor
the same canonical rows and policy predicate. Soft-revoked history and policy
versions remain valid data. The IPLF-026A migration downgrade/re-upgrade gate
remains the database rollback contract.
