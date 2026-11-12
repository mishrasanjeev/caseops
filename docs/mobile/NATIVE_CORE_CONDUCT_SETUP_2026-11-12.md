# Native Core workspace-rules setup — 2026-11-12

J20/M22, US-MOB-01 through US-MOB-08: implementation **Partially implemented**,
user-facing release verdict **Inconclusive**, store release **NO-GO**. Neither
store has a verified submission. This change repairs the isolated fixture; it
does not bypass production rules or certify the remaining native cases.

## Observed failure

The complete c8dd iOS Core23 run finished all 69 phases and paired all 23 unique
Appium session creations/deletions. Only the first eight cases passed all their
phases. There were 14 failed phases and eight unexecuted calls; postflight failed
with seven route rejections, no marker rejection and no overflow. Original
reports and independent reconciliation remain in the task cache under
`iosc8dd-core-full-02`. Contrary to the first incomplete interpretation of its
trace, NATIVE-09 found and opened the exact Matter and clicked Add note. Its
first missing control was **note-input**, after entering the rules gate.

The native XML then showed the rules-check error. The actual gateway admission
omitted GET /api/account/workspace-conduct. This is an authenticated native-only
endpoint: a normal browser Bearer session received 403 during an experimental
setup candidate. That stopped candidate is retained; it was removed from the
implementation. No browser credential is substituted for native authorization.

## Correction and native proof

Initial and extended Core admission now include exactly the policy GET. They
still exclude POST /api/account/workspace-conduct/accept. A setup-only native
helper accepts through the actual app control, checks its viewport frame and
on iOS its hittability, then requires the note editor. It dispatches once through
the protocol click, preserves lost acknowledgements, and grants no full-case
credit. Production and non-synthetic fixtures are refused.

Before freezing the next run, the operator admitted the one exact acceptance
POST temporarily for a fresh synthetic member. On the unchanged c8dd Simulator
app, native consent succeeded with a visible, hittable 269 by 51-point control;
one actual acceptance POST returned 200, the following policy GET returned 200,
and the note editor opened. The member signed out and the Appium session was
deleted. The temporary POST was then removed, retaining only the policy GET.
The immutable route/status snapshot was recaptured for the new run. Source-bound
native proof is retained in `iosc8dd-conduct-native-03`, and route restoration in
`iosc8dd-conduct-route-02/seal.json`, under the same task cache.

Earlier observations are separate: the completed first suite had revoked its
native session; two follow-ups reached compatibility/sign-out instead of consent.
A host observer import error also stopped before policy mutation. None receives
case credit or overwrites the failed full run.

A fresh Safari/MFA/PKCE observation and logout passed separately in
`iosc8dd-auth-03`. Complete replacement Core23 is running in
`iosc8dd-core-full-03`; it is **not passed** until its native inventory, all phases,
postflight, exact bundle/source/backend and session cleanup are reconciled.

## Regression coverage

`local-fixture.test.py` checks the complete exact initial route inventory and
extended Android/iOS route admission, preserves dynamic policy, and refuses a
standing acceptance mutation. `ios-native-locators.test.mjs` covers both
platforms, native postconditions, production refusal, viewport/hittability
failure, lost mutation acknowledgement and missing editor without replay.
The complete locator module passed 58 cases. A broader experimental Python run
used the wrong host runtime/dependency path and remains incomplete; the pinned
runtime replacement passed. A final source gate on the committed candidate
remains required. No native, production, signed archive or store pass is inferred
from these unit contracts.
