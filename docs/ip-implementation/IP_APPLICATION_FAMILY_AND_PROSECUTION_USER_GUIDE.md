# Application family and prosecution user guide

Last updated: 22 August 2026

## Open and group the register

1. Open **IP > Portfolio**. Existing access rules determine which applications
   are returned.
2. Use search and filters before changing the view; the same scope is applied
   to list, grid, and family results.
3. Select **Family view**. Choose **Mark families** to group applications of one
   existing asset, or **Client families** to group Matters assigned to the same
   canonical primary client.
4. Open a member to work on that specific docket. A family does not share an
   application number, phase, deadline, event, or lifecycle version.
5. Use **Load more families** when present. Pagination returns complete
   families, so a member set is not split across pages.

An ungrouped count means an accessible application has no usable family key.
Correct the asset or canonical Matter-client assignment instead of trying to
merge application history.

## Record a prosecution event

1. Open the target IP docket and find **Prosecution events**.
2. Select the exact application when the docket has more than one.
3. Choose the event type and effective time. Add the reason, evidence and
   document references required by the available source.
4. For registry data, provide the registry source reference. New registry facts
   remain candidates until reconciled.
5. Optionally select inward or outward correspondence and record the applicable
   received, due, prepared, approved, filed, and accepted timestamps.
6. Select **Preview prosecution event**. Review the proposed phase, checklist,
   duplicate candidates, recalculation signal, and unresolved exceptions.
7. Select **Record prosecution event** only when the preview is current and the
   required exception decisions are complete.

The checklist is a control aid. It does not prove that a form was filed, a fee
was paid, a registry accepted the filing, or a right reached final disposition.

## Correct, reconcile, and backdate

- **Correct event** starts a superseding-event flow. Enter why the correction
  is required; the original event remains in the immutable timeline.
- **Reconcile candidate** starts a registry decision. Choose **Same legal
  fact**, **Keep separate**, or **Reject candidate**, preview, and then record.
- A possible manual duplicate cannot be committed as another confirmed fact
  until an explicit reconciliation is selected.
- A backdated event requires acknowledgement of the recalculation preview. It
  is appended to history, while a later accepted phase remains current.
- A stale lifecycle or application version fails closed. Reload the docket and
  repeat preview against current data.

## Read the timeline

The workspace shows current phase, registry freshness, data-quality gaps,
unconfirmed deadlines, conflicting facts, and separate counts for operational
completion, filing evidence, registry acceptance, and final disposition. Each
timeline row identifies candidate status, source and time, phase movement,
correction/reconciliation links, correspondence, documents, and deadline
references where present.

## Permissions and support boundary

Read and write operations enforce tenant, capability, restricted-Matter, and IP
workspace entitlement checks on the server. The family route is a read model;
it does not create a new legal record. CaseOps records and controls the work but
does not itself file, pay, notify a registry, or create legal acceptance.
