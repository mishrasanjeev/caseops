# Round 5: Adversarial Scope And Contract Review

Date: 23 October 2026. Method: independent expert critique followed by parent
integration. Input: R01-R04 and read-only repository inspection at e3b20ee6.
Reviewers: parent Codex; UX sidecar Lorentz; architecture sidecar Huygens.
No participant trial, app code, provider call or native test occurred.

## Findings Against Revision 4

1. Today accepts a horizon, not a My/Team ownership switch. Its tasks can include
   unassigned work. Relabeling current visible work as personal would mislead.
2. The current Today streams do not supply the promised contract-obligation and
   general-renewal streams. A GC proposition needs actual bounded read contracts.
3. Existing draft reviewer notes perform `request_changes`; they are not a
   neutral comment command. A review UI must not conceal that transition.
4. Remembering a tab/scroll position is not proof of current access. The current
   Today hearing DTO does not establish a source-check timestamp.
5. Today and Work overlap without a definition for undated work and continuation.
6. Online-first excludes persistent court packs. Upload staging is not an
   offline cache, and external sharing has a separate confidentiality boundary.
7. The existing Notifications navigation is preferences, not a general inbox.
   Native push/device registration was not found. Account identity needs an
   actual workspace name, not a generic Workspace label.
8. Bearer compatibility does not establish native sessions: current refresh
   requires a still-valid access token and logout clears browser cookies.
   Device-specific revocation, rotation and secure native handoff are new work.

## Revision 5: Decisions Incorporated In The Final Plan

- Add an explicit current-source-to-screen matrix. Mark unsupported read
  composition, ownership filters, native sessions, inbox and push as missing
  or partially implemented; require bounded backend contracts before UI claims.
- Today is time-sensitive triage. Work is the full supported assignment/review
  queue, including undated work. Both use the same originating identities,
  authoritative status, scope predicate, counts and continuation contract.
- Design My work and permitted Team scope as a proposed addition, not an
  existing Today parameter. Define owner/assignee and unassigned semantics per
  stream; never infer team membership from the phone's chosen mode.
- V1 review is reading exact existing revisions/sources and supported neutral
  notes/annotations only. Draft request-changes, approval, recommendation
  decisions and finalization remain explicit web workflows, not generic comments.
- Foreground/resume revalidates authority and server data before revealing a
  retained destination. Distinguish Loaded at, Source checked at, Manual date,
  Stale source and Freshness unknown. A read refresh never calls paid sync.
- An inbox entry point is a labeled notification icon in Today. The global
  bounded read model/device transport must actually be implemented before it
  appears; preferences are not an inbox. Read/dismiss never completes a task.
- Show the actual permitted workspace name; signed-in person is one action away.
  Authenticated cross-workspace switching is a P0 contract gap. Until proven,
  changing workspace requires an explicit logout and new login, with full purge.
- Exclude external document export/share in v1. Read existing hearing packs and
  files online with page/source navigation and return position. Native temp
  staging/viewer bytes have bounded cleanup; no private durable offline promise.
- Require native credential precedence, refresh/revoke and MFA/session binding
  proof. Preserve browser auth/CSRF and portal/platform separation unchanged.

## Result And Remaining Gate

Five sequential design rounds are documented. The final four-tab concept is
coherent enough for a feasibility spike and design prototype, with the identified
contract gaps recorded rather than hidden. Native release readiness is NO-GO:
no native app or mobile test inventory has executed. All UX timing/task success
figures in the final plan are future targets, not measured outcomes.

Next: P0 native-session and two-platform build proof, then clickable prototype
and participant trials. This review does not authorize an unreviewed cloud spend,
production schema mutation, app-store submission or broad phone feature build.
