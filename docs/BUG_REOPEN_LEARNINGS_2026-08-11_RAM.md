# Ram 2026-08-11: Brutal Regression and Matter-Reopen Audit

## Verdicts

- **BUG-001 is valid.** The Matter filter grid used six fixed columns at
  desktop widths. At widths below the design's widest breakpoint, the rendered
  Max Claim control could leave the visible panel even though it still existed
  in the DOM.
- **BUG-002 is valid and systemic.** All seven Grounded Research modes shared
  an unbounded synchronous retrieval path. It was not seven independent UI
  defects and a larger browser timeout would only hide the failure.
- **The manual Matter forum request is a valid enhancement.** The existing
  forum master covered several court families, but the requested specialist
  forums and consumer presentation were incomplete, and bulk import could
  accept free text instead of using the manual-entry master.
- **Matter reopening is an adjacent lifecycle audit, not a row in the supplied
  workbook.** It remains a release-blocking regression concern because a
  terminal row becoming operational silently is a data-integrity failure.

## Where the earlier approach failed

1. **Evidence stopped too early.** A source-tree test was treated as if it
   proved the deployed system. Historical production replay showed behavior
   that differed from the local candidate. Build identity, migration head,
   deployed revision, traffic target, and the dated production replay all need
   to refer to the same commit.
2. **Responsive tests asserted existence, not visibility.** A locator can be
   attached while its right edge is outside the panel. Acceptance must compare
   real bounding boxes and horizontal scroll widths at narrow, tablet, and
   desktop viewports, including every grouped action.
3. **Research was tested with a toy corpus.** The old request performed
   repeated large-table aggregates, multiple sequential query-embedding calls,
   over-fetched documents, then lazily loaded every chunk for every candidate.
   It also ran synchronous database/provider work directly on the ASGI event
   loop. A browser abort did not cancel that server work. On a production corpus
   and a concurrency-one service, abandoned searches could therefore occupy the
   API long enough to make login and Matter requests appear broken too.
4. **The forum hierarchy had two sources of truth.** Manual entry used the
   catalog while bulk import accepted category/name strings. A UI-only addition
   would have left bulk import able to create invalid or unlinked forum data.
5. **The word “reopen” was underspecified.** A controlled
   `Disposed -> Intake` lifecycle transition is intentional. A later explicit
   `Intake -> Active` transition is also distinct from a disposed row being
   silently reactivated. The regression must prove the actual invariant at the
   API, persistence, child-operation, operational-view, and audit boundaries
   instead of inferring it from one status label.

## Why disposed Matters could appear to reopen

The previously observed production failure was deployment drift: production
accepted behavior that the then-current local lifecycle suite rejected. The
present source has one legal terminal-state owner: the lifecycle endpoint locks
the parent, verifies expected status and `updated_at`, changes status,
`is_active`, and lifecycle version atomically, records the audit event, and
neutralizes operational children. Generic PATCH rejects disposed or inactive
rows and cannot set `disposed`; imports only create new rows; workers and child
services use the shared operational guard.

The controlled reopen deliberately lands in **Intake**, not Active. It does not
resurrect old tasks, deadlines, hearings, reminders, sync jobs, notification
deliveries, or stale next-hearing state. A user can later make a separate,
audited non-terminal transition; that is not an automatic terminal escape.

## Permanent prevention rules

1. Run the same dated Playwright spec against the current local build and the
   exact deployed revision. Verify release SHA before and after production QA.
2. Lifecycle proof must include disposal, stale-write rejection, generic PATCH
   rejection, child-create rejection, Today/calendar suppression, controlled
   reopen to Intake, no child resurrection, audit actions, and persistence after
   reload. Finish in Disposed and reload once more.
3. Performance regressions need an explicit work budget: bounded candidates,
   bounded child rows, constant query count, batched provider calls, provider
   deadlines, and production-scale timing. After a timed-out request, probe an
   unrelated endpoint so request abandonment cannot hide API starvation.
4. Responsive regressions must assert the visible surface, container overflow,
   and the bounds of every control at 390px, 1024px, and 1280px or equivalent
   product breakpoints.
5. Any new hierarchy offered by both manual and bulk creation must have one
   server-owned active master. Persist its ID and derived lineage, revalidate on
   preview and commit, and reject ambiguous/invented values. If a historical
   import contract needs a compatibility path, keep it explicit and narrower
   than the new catalog-backed categories.
6. Never classify a release as fixed from source tests alone. Record commit,
   image/revision, migration, traffic, local build, local replay, production
   replay, cleanup, and final persisted state.
