# Ram 24 August 2026 — bug analysis and permanent learnings

## Source reconciliation

The supplied workbook has two populated issue rows. Its Summary tab describes
four unrelated older items, so the Summary is stale copied content and cannot
be used as the issue count or acceptance scope.

## BUG-001 — trademark portfolio first control is cut off

### Verdict

Valid responsive UI bug.

### Root cause

The control bar changed to a single horizontal row at the `xl` browser
breakpoint. At a 1280 px browser width the application sidebar left roughly
960 px for page content, while the row contained four fixed-width selectors,
two actions, and a search form. Flexbox legally shrank the search form until
the search input became unusable and overlapped the next control. The earlier
`min-w-0` change only allowed shrinking; it did not preserve useful width.

### Where the earlier approach was shallow

- It reasoned from viewport width rather than the page's available content
  width after navigation.
- It treated absence of horizontal scroll as proof of visibility.
- It did not assert the rendered width or non-overlap of every control at the
  actual failing desktop width.

### Permanent prevention

Control rows wrap by default and only condense at a breakpoint with enough
real content width. The dated Playwright regression checks 390, 1280, 1440,
and 1536 px; every control must be visible, inside the viewport, wider than a
minimum useful size, and the search field must not overlap its action.

## BUG-002 — Create Non-Executable Dry Run does not work

### Verdict

The current backend operation is functional with valid machine-level inputs,
so the report is not a backend outage. It is a valid product workflow defect:
the page required a legal user to type an internal registered class ID, target
type, candidate count, and a 64-character SHA-256 tenant reference, then hid
specific API errors behind a generic message.

### Root cause

The original UI exposed the low-level evidence schema directly instead of
providing an operator workflow. It also added request/approve/reject gates to a
record that cannot execute anything, creating ceremony without adding safety.

### Where the earlier approach was shallow

- A successful API unit test was mistaken for a usable browser workflow.
- The browser was made responsible for server-owned tenant identity and catalog
  values.
- Generic error handling prevented the operator from correcting input.
- A manual approval contract was built around a permanently non-executable
  artifact.

### Permanent prevention

The API now exposes the reviewed data-class catalog and a tenant-scoped dry-run
endpoint. It derives the tenant hash and candidate count from the authenticated
workspace and trusted table metadata. The UI only asks for the operation,
registered class, and optional evidence. Manual review routes and their stale
capability/UI are removed; execution remains machine-blocked with HTTP 503.

## Why Matters appeared to reopen

The historical defect was architectural: generic Matter updates accepted stale
full-record payloads, lifecycle state was not isolated behind one transition
boundary, and child/background paths could make terminal records operational
again. A UI-only patch could not solve that.

The current implementation centralizes disposal and reopening in the dedicated
lifecycle endpoint. It locks the parent, requires optimistic concurrency,
changes status/is_active/lifecycle version/audit/children atomically, refuses
generic reactivation, and suppresses disposed Matters from operational views.
The only permitted reopen is the explicit, audited `Disposed -> Intake`
transition; a later `Intake -> Active` is another explicit event. That controlled
workflow must not be reported as silent resurrection.

The permanent lifecycle regression proves disposal, stale-write rejection,
generic PATCH refusal, child-creation refusal, operational-view suppression,
controlled reopen to Intake, no child resurrection, audit distinction, reload
persistence, and final return to Disposed. The same dated spec must run locally
and against the exact production release.

## Completion rule

Source tests are preparation, not closure. These items can be marked fixed only
after the same dated Playwright cases pass against a fresh local production
build, the validated commit is on `main`, production serves that exact SHA for
both API and web, and the same cases pass against production.
