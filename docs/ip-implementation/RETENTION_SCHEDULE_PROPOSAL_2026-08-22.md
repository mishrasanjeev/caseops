# Retention schedule — **proposal for legal approval**, not an approved schedule

**Status:** `proposed`. Nothing here is authorised, and no purge may be
authorised on the strength of this document.
**Prepared by:** Claude (engineering), 2026-08-22, at the repository owner's
request to move `IPLF-028A-POLICY-AND-HOLD-AUTHORIZATION` forward.
**Required before it means anything:** approval by a qualified
legal/privacy owner through the `propose_version → approve_version →
activate_version` lifecycle, under four eyes and step-up.

---

## Why this is a proposal and not a decision

The blocker says, correctly:

> which classes are kept, for how long, on what legal basis is a **legal
> decision**, and while none exists a retention purge cannot be authorized at all

I am not a qualified legal owner and cannot supply that decision. What I can do
— and what this document is — is remove every *engineering* reason the decision
is hard to make: name the classes that actually exist, state what each one holds,
propose a period with the reasoning that suggests it, and identify the statute a
lawyer would need to confirm or correct.

**A reviewer's job here is to correct the periods and bases, not to accept
them.** The durations below are starting positions derived from the character of
the data, not legal advice. Several are almost certainly wrong in ways only an
Indian legal practitioner will spot.

## Scope

The six data classes admitted by the reviewed data-class projection. This is the
complete set the runtime will govern; anything outside it cannot be purged
because it is not registered.

| Data class | What it holds | Proposed retention | Reasoning that suggests it | Statute to confirm |
|---|---|---|---|---|
| `legal_holds` | The hold record: authority reference, scope, who created and approved it | **Permanent** while active; **7 years** after release | A hold is the evidence that preservation was ordered and honoured. Destroying it destroys the proof that the firm complied | Limitation Act 1963 (3 yr general, 12 yr for some property claims); Advocates Act / BCI rules on client records |
| `legal_hold_items` | The specific records a hold preserves | Follows the parent hold | Splitting item retention from hold retention would leave a hold that cannot say what it preserved | as above |
| `data_retention_policies` | The policy identity | **Permanent** | The audit question "under what rule was this purged?" must remain answerable after the rule is retired | DPDP Act 2023 accountability duties |
| `data_retention_versions` | Immutable versioned terms, approvals, activation | **Permanent** | Same. These rows are the authorisation record for every purge performed under them | DPDP Act 2023 |
| `tenant_data_operations` | Export/purge/offboarding manifests, approvals, refusals | **7 years** | This is the record of who asked to delete or export tenant data, who approved, and who refused. It is the primary artefact in any dispute about a deletion | DPDP Act 2023; Companies Act 2013 s.128 (8 yr for books of account, if any operation touches them) |
| `tenant_data_operation_items` | Per-target rows inside a manifest, hashed | Follows the parent operation | An operation without its items cannot show what it would have touched | as above |

## The pattern in the table, and why a reviewer should distrust it

Every proposed period above is **long or permanent**, and all six classes are
governance metadata rather than client data. That is not a coincidence and it is
not conservatism for its own sake: these six rows are the record of what was
done to other data. Purging them is the one deletion that destroys the ability
to audit deletions.

The consequence a reviewer should weigh: **this schedule, if approved as
written, authorises almost no purging.** That may be exactly right for these six
classes. It also means approving it does not unblock any real
export/purge/offboarding workflow — those touch client data classes that are not
yet registered. If the intent is to unblock those, the missing step is
registering them, not approving this.

## What is deliberately absent

- **Client matter files, documents, communications, billing records.** Not in
  the admitted set, so out of scope here. These are where the genuinely
  contentious retention questions live — BCI rules, engagement terms, and the
  client's own instructions all bear on them, and they vary per firm and per
  matter.
- **Tenant-configurable bounds.** The schema supports per-tenant variation. A
  firm with a regulator-mandated period needs to set it; this proposal does not
  attempt a one-size default for that.
- **Jurisdiction exceptions.** Proposed as a single Indian-law baseline. A
  tenant operating under another regime needs its own version.

## How to approve it, if a legal owner agrees

1. `propose_version` with the terms, recording the proposer. This authorises
   nothing.
2. A **different** person calls `approve_version` under step-up — four eyes is
   enforced against the recorded proposer and by the database.
3. `activate_version` puts it in force and supersedes any previous active
   version, so a purge has exactly one answer about how long to keep a record.

Steps 2 and 3 require a recent MFA step-up for `retention_policy_activation`
specifically, and that is unconditional — see `EH-SEC-01` in the gap ledger.

## What this does not change

`IPLF-028A-POLICY-AND-HOLD-AUTHORIZATION` **stays open.** A proposal is not an
approval, and the blocker closes when a named legal owner has approved schedule
content — not when someone has drafted some. `approve_execution` still refuses a
retention purge that cites no active version, and nothing in this document
should be read as authorising a purge.
