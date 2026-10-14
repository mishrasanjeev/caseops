# Calendar Acceptance Follow-Up, 14 October 2026

## Scope And Source

Independent follow-up from `655c803a1910514944c9c609767dfd27f0b75b35`
(tree `f41d4c599b0c352fed98e36b171b841433e5f50d`). This does not
change the frozen 655 acceptance candidate or certify a production release.
PRD mapping: J08 / M08 / MOD-TS-006; US-022 through US-025;
FT-042/043 and FT-078 through FT-082; SEC-003/004 and NFT-007.

The original IP document allows existing URL/file-reference attachment
models. This follow-up adds no embedded-image requirement. It does not recreate
the missing original IP register or identify the unknown LIFE-13 Matter.

## Demonstrated Ordering Regression

The same six aggregation regressions pass against the immutable base
`30e7229368de013123e9a48db2b19230829ddac2` Calendar module and fail in
the call phase against unchanged 655. Each full error is retained independently.
Equal-date/title task and deadline rows were reordered by Matter/event IDs.
Two of the six cases prove that irrelevant hearing-time metadata must not
influence those kinds; current collectors do not normally populate that field.

Only hearing-time, Matter-ID and event-ID sort keys are now hearing-only.
Hearing court/time/title/ID ordering is unchanged. Non-hearing ties regain
the legacy stable input order; this does not promise a new SQL tie order.
The base comparison substitutes the exact old aggregation module with current
DTO dependencies, not an entire historical application/database deployment.

## Acceptance Added

| Contract | Regression |
| --- | --- |
| Actual Calendar event navigation | Both existing dated cases click an owned overflow hearing, require a successful exact-Matter workspace response, assert its exact hearing source, loaded Matter heading/code and visible hearing purpose/date, then return to Calendar. |
| Responsive complete journey | Existing month/week/day/session/overflow/reload assertions remain, at 1280px and 393px; the loaded Matter page also remains within the viewport. |
| Loading versus empty/error | Calendar component tests retain a delayed request without a false empty state, then show its event; rejection shows the real error and recovers only after an explicit Try again. |
| Non-hearing compatibility | Six exact stable-order cases cover task/deadline Matter-ID, event-ID and irrelevant hearing-time ties. Existing SQLite HTTP and native PostgreSQL identities remain discoverable. |

## Evidence And Limits

Outside evidence: `outputs/calendar-ip-20261013/calendar-acceptance-followup-20261014-01`.
It retains the base pass, all six 655 failures, component attempt/correction,
ordered pytest phases/JUnit and browser results. Initial local API/browser
diagnostics passed their assertions but their whole-source check detected
Next development's generated declaration change; they are not clean acceptance.
The complete component replacement passed 19 cases. Clean-commit replay receipts
are recorded in the outside handoff after this document is committed.

Verdict: **Inconclusive for production closure**. Exact joined-source native,
Docker, hosted and deployed browser acceptance remain parent-owned. Native-only
skips in a SQLite run are unverified, not passes. Source-renewal delivery is a
separate parent-owned follow-up. No provider, cloud or production mutation was
performed by this workstream.
