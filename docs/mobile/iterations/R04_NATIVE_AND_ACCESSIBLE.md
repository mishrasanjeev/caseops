# Round 4: One-Handed, Accessible And Platform-Native

Date: 23 October 2026. Method: layout and interaction walkthrough of Revision 3.
Input: safe-state flows from Round 3 plus current Apple/Android guidance.
Sources are linked in the parent mobile plan; no native pixels have been tested.

## Critique Of Revision 3

- Correct permission and stale-state logic is not enough if its label is tiny.
- A phone cannot reasonably show a full desktop month grid and readable events.
- Two rows of tabs consume the viewport and compete with the software keyboard.
- Swipe-only actions, hover menus and unlabeled status colors exclude users.
- Asking a user to scan a QR shown on the same phone repeats the MFA setup issue.
- A local biometric unlock can be mistaken for server MFA or a fresh approval.

## Revision 4

### Layout

- Four labeled bottom destinations. Each retains its own back stack and list
  position. Account/settings is a header control, not a catch-all More tab.
- Calendar opens on the day agenda with week navigation. A month picker selects
  a date; selecting it opens the complete agenda. Counts never hide unreachable
  events. Filters identify hearing, task, obligation or IP deadline explicitly.
- Use vertically stacked matter rows, not shrunken tables. Show matter code,
  title, parent/client as permitted, status and next date without truncating the
  distinguishing identifier. Large text may increase row height.
- Keep one primary contextual action. Editing uses a full-height screen when
  the keyboard is involved, with a visible parent, explicit Save and Cancel,
  field-level errors and keyboard-safe action placement. Sheets suit short
  choices, not multi-step legal work. Unsaved navigation prompts only when needed.
- On iPad and Android tablets, use list/detail panes when space allows. Do not
  stretch a phone card across a tablet or require landscape for core jobs.

### Input And Accessibility

- Minimum targets: iOS 44 x 44 pt, Android 48 x 48 dp; distinct hit areas must
  not overlap. Test text scaling to 200%, VoiceOver and TalkBack reading order.
- Body text uses a fixed accessible scale with platform text scaling, not
  viewport-relative font sizes. Preserve existing brand type where it passes
  native rendering and bundled-font/license checks; platform conventions win
  where required for native controls. No new font procurement.
- Use text plus shape/icon for statuses. Normal text contrast target 4.5:1;
  large text 3:1. Honor reduced motion, focus, safe areas and screen rotation.
- Match Android system/predictive Back and iOS back gesture. No essential action
  depends on swipe, long press, hover, tiny overflow or a gesture tutorial.
- Password-manager autofill and OTP paste are supported. During future native
  authenticator enrollment offer an on-device authenticator handoff if supported,
  plus private manual entry; retain QR for use with another device. Never put
  MFA secrets into an external QR service. Biometric unlock is local convenience,
  not a substitute for server-required MFA or recent step-up.

### Revised Phone Wireframe

Illustrative planning wireframe only; labels below are not customer records.

```text
+-----------------------------------+
| CaseOps       Workspace   Account |
| Today                    Search   |
| My work     Fri 23 Oct             |
|-----------------------------------|
| Next                              |
| 10:30  Hearing                     |
| MAT-104  Sample matter             |
| Source checked: [timestamp]        |
|                                   |
| Due today                         |
| Confirmed deadline                |
| MAT-118  Sample matter             |
|                                   |
| Assigned                          |
| Review current document           |
| MAT-121  Sample matter             |
|-----------------------------------|
| Today | Matters | Calendar | Work  |
+-----------------------------------+
```

## Walkthrough Result

Every important action now has a visible non-gesture path. Agenda rows expose
all events; long content can grow vertically. Authentication does not require
scanning the same phone. These are design decisions, not pixel, screen-reader
or physical-device acceptance. Round 5 must challenge the combined design for
scope creep, terminology ambiguity and executable release gates.
