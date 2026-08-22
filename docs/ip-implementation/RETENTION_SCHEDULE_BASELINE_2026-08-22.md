# Retention schedule — assumed engineering baseline

**Status:** `assumed_baseline`. These are working values adopted so the slice
stops blocking, on the repository owner's instruction of 2026-08-22 ("assume a
suitable number and go ahead, do not block for this").

**What that does and does not mean.** It means engineering has a concrete
schedule to build and test against, and that `IPLF-028A` no longer waits on a
legal decision to make progress. It does **not** mean these periods are legally
correct, and it does not authorise a purge: no version has been activated, and
`approve_execution` still refuses a retention purge citing no active version.

**Still required, just no longer blocking:** confirmation or correction by a
qualified legal/privacy owner, through
`propose_version → approve_version → activate_version` under four eyes and
step-up. Until that happens these are an engineer's assumption wearing a
schedule's clothes, and the label above says so.

---

## How these numbers were chosen, so they can be argued with

I am not a qualified legal owner. What follows is derived from the *character*
of each data class — what it holds, and what is lost if it is destroyed — with
the statute a practitioner would need to confirm named alongside. That is a
defensible engineering baseline and it is not legal advice.

**A reviewer's job is still to correct these, not accept them.** Several are
probably wrong in ways only an Indian practitioner will spot. The difference
from an hour ago is that being wrong now costs a correction rather than a
blocked slice.

## Scope

The six data classes admitted by the reviewed data-class projection. This is the
complete set the runtime will govern; anything outside it cannot be purged
because it is not registered.

| Data class | What it holds | Assumed retention | Reasoning | Statute to confirm |
|---|---|---|---|---|
| `legal_holds` | The hold record: authority reference, scope, who created and approved it | **Permanent** while active; **7 years** after release | A hold is the evidence that preservation was ordered and honoured. Destroying it destroys the proof that the firm complied | Limitation Act 1963 (3 yr general, 12 yr for some property claims); Advocates Act / BCI rules on client records |
| `legal_hold_items` | The specific records a hold preserves | Follows the parent hold | Splitting item retention from hold retention would leave a hold that cannot say what it preserved | as above |
| `data_retention_policies` | The policy identity | **Permanent** | The audit question "under what rule was this purged?" must remain answerable after the rule is retired | DPDP Act 2023 accountability duties |
| `data_retention_versions` | Immutable versioned terms, approvals, activation | **Permanent** | Same. These rows are the authorisation record for every purge performed under them | DPDP Act 2023 |
| `tenant_data_operations` | Export/purge/offboarding manifests, approvals, refusals | **7 years** | This is the record of who asked to delete or export tenant data, who approved, and who refused. It is the primary artefact in any dispute about a deletion | DPDP Act 2023; Companies Act 2013 s.128 (8 yr for books of account, if any operation touches them) |
| `tenant_data_operation_items` | Per-target rows inside a manifest, hashed | Follows the parent operation | An operation without its items cannot show what it would have touched | as above |

## The pattern in the table, and why it matters more than the numbers

Every proposed period above is **long or permanent**, and all six classes are
governance metadata rather than client data. That is not a coincidence and it is
not conservatism for its own sake: these six rows are the record of what was
done to other data. Purging them is the one deletion that destroys the ability
to audit deletions.

The consequence, which survives whatever the reviewer does to the periods:
**this schedule authorises almost no purging.** That is probably right for these
six classes. It also means adopting it does not unblock any real
export/purge/offboarding workflow — those touch client data classes that are
**not yet registered**, so they cannot be purged regardless of what any schedule
says.

That is the finding worth carrying forward. The retention-content question was
never the thing standing between here and a working purge workflow; the
unregistered client-data classes are. Recorded as `IPLF-028A-DATA-CLASS-COVERAGE`
so the next person does not re-derive it.

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

## How to put it in force, when a legal owner has confirmed it

1. `propose_version` with the terms, recording the proposer. This authorises
   nothing.
2. A **different** person calls `approve_version` under step-up — four eyes is
   enforced against the recorded proposer and by the database.
3. `activate_version` puts it in force and supersedes any previous active
   version, so a purge has exactly one answer about how long to keep a record.

Steps 2 and 3 require a recent MFA step-up for `retention_policy_activation`
specifically, and that is unconditional — see `EH-SEC-01` in the gap ledger.

## What this does not change

`IPLF-028A-POLICY-AND-HOLD-AUTHORIZATION` narrows but **does not close**. The
content question is answered well enough to build on; it is not answered
*authoritatively*, and the blocker's own words are that this is a legal
decision. What changes is that it is no longer a reason to stop.

Unchanged: no version is activated, `approve_execution` still refuses a
retention purge citing no active version, and nothing here authorises a purge.
