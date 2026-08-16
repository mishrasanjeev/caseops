# Owner waiver of named human sign-off gates

**Date:** 2026-08-14
**Decided by:** Sanjeev Kumar, CaseOps repository and program owner
**Scope:** `PRD-IPLF-2026-08-01` (`docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md`)
**Recorded by:** Claude Opus 5, acting on the owner's explicit instruction

## Decision

The program owner has removed the requirement for **named specific sign-offs**
across the IP Law Firm program. Every row whose `acceptance_status` was
`pending` solely because it awaited a named human approver is recorded as
`not_required` under this waiver.

This is recorded as an **owner waiver**, not as approval. No lawyer, security
reviewer, privacy owner, provider owner, SRE, product owner, or pilot customer
has reviewed or signed anything. No signature, checkbox, or reviewer name has
been generated. Any future claim that a qualified professional accepted this
work would be false.

## What this waiver does and does not change

It changes **only** `acceptance_status`. It does not change:

- `implementation_status` — code still has to exist.
- `verification_status` — tests still have to pass.
- `release_status` — a row is still `blocked` until it is actually built,
  deployed, and verified against the exact serving revision.

A slice that is unimplemented, untested, or undeployed remains exactly as
incomplete as it was before this waiver. The waiver cannot make the program
compute complete on its own.

## Gates waived

| Gate | Was blocked on | Status now |
|---|---|---|
| `M0-HUMAN-PROGRAM-LOCK` | Named Product, legal, security, data, SRE and pilot approvals per PRD §24 and §26.4 | Owner-waived |
| `M1-RESEARCH-GOLDEN-LAWYER` | Named legal research reviewer approving 3 golden-query fixtures | Owner-waived |

## Risk the owner has accepted

These gates existed because this is legal software used on real client matters.
Waiving them means:

1. **The IP research golden-query set carries no lawyer review.** The three
   fixtures in `apps/api/tests/fixtures/research/ip_golden_queries.json` remain
   unreviewed. They can no longer be described as legal-quality acceptance
   evidence; they are synthetic developer fixtures.
2. **M8-M10 domain automation carries no specialist review.** Patents, designs,
   copyright, geographical indications, plant varieties, semiconductor layout
   designs, trade secrets, domains, customs and licensing automation may now be
   implemented without the named specialist review the PRD required before
   activating domain-specific legal automation.
3. **No pilot, security, privacy or provider owner has accepted the program.**

## Controls that remain in force

This waiver does **not** authorise any of the following, which remain blocked by
platform safety rules independent of acceptance status:

- Sending messages to real clients, opposing parties, courts, registries, or
  unapproved recipients.
- Submitting a legal filing, effecting service, paying a fee, collecting or
  refunding money, waiving a right, accepting a settlement, or closing a matter.
- Activating an unverified legal rule, fee, form, workflow, authoritative text,
  provider, or source.
- Irreversible production deletion, tenant purge, or retention destruction.
- Representing generated content as reviewed by a qualified legal professional.

Legal-rule activation still requires two distinct qualified actors inside the
product (`RULE-GOV-03`), and every declared legal fixture must still pass. That
is an in-product control, not a program sign-off, and this waiver does not
touch it.

## Reversal

Delete this waiver and reset the affected `acceptance_status` values to
`pending` to restore the original gating. The `not_required_approval` block on
each row cites this document, so the affected rows are recoverable with:

```
grep -c "OWNER_ACCEPTANCE_WAIVER_2026-08-14" docs/ip-implementation/PROGRAM_MANIFEST.yaml
```
