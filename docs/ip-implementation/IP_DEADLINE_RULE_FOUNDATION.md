# IP deadline, rule, calendar, and responsibility foundation

**Slice:** `IPLF-023A`  
**Status:** Repository implementation and local verification complete; independent CI, canonical-main release, production deployment, and human acceptance remain pending.  
**Program status:** `PROGRAM INCOMPLETE`

## Ownership boundary

`ip_deadlines` owns legal calculation, source, confirmation, override, lifecycle,
and completion evidence. It is deliberately not a second operational deadline
board. `matter_deadlines` remains the only editable operational deadline owner
for Matter, calendar, Today, and reminder consumers.

The bridge is one-way and unique:

1. legal evidence is calculated and reviewed in `ip_deadlines`;
2. a later guarded confirmation command may ask the existing deadline service
   to create one `MatterDeadline` with `source_ref_type=ip_deadline` and
   `source_ref_id=<ip deadline id>`;
3. `ip_deadlines.matter_deadline_id` records that projection, with a database
   uniqueness constraint preventing two legal rows from claiming one
   operational deadline;
4. operational edits never rewrite the stored rule, calendar, inputs, trace, or
   original legal result.

`legal_working_calendars` and their append-only versions are neutral shared
platform records. They are not IP-only calendar events and do not replace
`CalendarEventSync`. `ip_rule_sets`/`ip_rule_versions` own public legal rule
evidence, while `company_ip_rule_policies` only selects an approved version and
records tenant auto-confirm eligibility. A tenant policy cannot turn a draft
rule into an approved rule.

## Persisted evidence

Migration `20260807_0005` adds seven tables:

| Table | Canonical purpose |
|---|---|
| `legal_working_calendars` | Company-scoped shared calendar identity by key, jurisdiction, and office |
| `legal_working_calendar_versions` | Immutable timezone, weekend, holiday, closure, exceptional-working-day, source-priority, effective-range, and approval evidence |
| `ip_rule_sets` | Stable deadline/form/fee rule identity scoped by jurisdiction, office, right, proceeding, role, and stage |
| `ip_rule_versions` | Immutable source/hash, engine compatibility, fixtures, definition, independent review, legal approval, activation, retirement, and emergency-disable evidence |
| `company_ip_rule_policies` | Versioned company selection and explicit auto-confirm/internal-target policy |
| `ip_deadlines` | Trigger, rule/calendar versions, exact inputs and intermediate operations, certainty/precision, result, citation, confirmation, override, completion, supersession, and operational correlation |
| `ip_responsibility_assignments` | Effective-dated primary, backup, supervisor, or docketing assignment with acknowledgement, delegation, replacement source, and escalation policy |

All tenant legal children carry company-scoped foreign keys. Rule, calendar,
deadline, and responsibility actor fields retain label snapshots where the
membership reference may later be unavailable. Confirmed calculations retain
their version identifiers and trace; changing a rule or calendar does not
silently mutate historical evidence.

## Fail-closed calculation contract

`calculate_ip_deadline` is deterministic and side-effect free. Its input
includes the exact rule version, source version, engine version, calendar
version, timezone, trigger, duration, direction, inclusion policy, extension,
and next-working-day policy. Its output includes the normalized input snapshot,
an ordered calculation trace, result, certainty, and plain-language
explanation.

The first engine boundary covers calendar days, business days, month
anniversaries, and year anniversaries, including before/after direction,
inclusive bases, leap/month-end clamping, explicit extensions, weekends,
holidays, exceptional working days, and next-working-day adjustment. It does
not collapse hearing/session precision, restoration/condonation, or legal
extensions into an untyped generic offset; those remain explicit rule
definition inputs for the completion workflow.

If a trigger is unknown, uncertain, or conflicting, the result is
`provisional` with no manufactured date. No calculation in this slice creates
a legal deadline, operational deadline, reminder, calendar event, provider
call, or external communication.

## Approval and responsibility controls

- Rule activation requires a reviewer and named legal approver who are both
  independent of the proposer and of each other.
- Every declared legal fixture must pass; an empty or partial fixture result
  fails closed.
- Critical deadline confirmation requires an acknowledged active primary plus
  acknowledged backup, supervisor, or docketing coverage.
- Production auto-confirm remains dark. The completion slice must enforce
  approved rule status, company policy, entitlement, rollout flag, and source
  determinism before it can be considered.

## Migration and rollback

The migration is additive from `20260807_0004` to `20260807_0005`. Downgrade
drops only the seven new foundation tables in dependency-safe order; it does
not change existing Matter deadlines, IP events, applications, or docket rows.
Automated evidence proves upgrade, downgrade to `0004`, and re-upgrade to
`0005` on a fresh database.

## Remaining boundary

`IPLF-023B` owns authenticated APIs, guarded proposal/approval/confirmation/
override/recalculation/completion commands, impact preview, operational
projection, exception queues, responsive UI, dated E2E, and production proof.
The reciprocal M3 slices remain responsible for domain activation depth. This
foundation must not be reported as completing `CAL-OPS`, `IP-DL`, `RULE-GOV`,
M2, or the overall IP program.

