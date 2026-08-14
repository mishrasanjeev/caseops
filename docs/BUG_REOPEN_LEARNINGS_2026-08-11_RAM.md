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
   The first corrective production replay exposed two more cold-path faults:
   the Research page requested corpus stats in parallel even though search
   already returned coverage, and PostgreSQL stats still performed an exact
   scan over the live 5,366,835-chunk / 827,758-document corpus. Interactive
   query tokenization also resolved a Hugging Face asset, while each reranked
   request reconstructed an ONNX session. The live planner then exposed full
   scans in exact-citation, judge, and Act/section paths; catalog estimates,
   bounded global vector probing, and concurrent trigram indexes now protect
   every shared search mode rather than only the originally failing keyword path.
4. **Release infrastructure retained stale revisions.** Historical preview
   tags combined with revision-level `minScale=1` kept old API revisions alive.
   Secret references are pinned when a revision is created, so those old
   instances repeatedly restarted with obsolete database credentials after
   rotation. That background churn amplified cold scaling and made one warm
   revision look healthy while the service as a whole was not converged.
5. **The forum hierarchy had two sources of truth.** Manual entry used the
   catalog while bulk import accepted category/name strings. A UI-only addition
   would have left bulk import able to create invalid or unlinked forum data.
6. **The word “reopen” was underspecified.** A controlled
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
5. **SUPERSEDED 2026-08-14 — see
   `docs/BUG_REOPEN_LEARNINGS_2026-08-14_RAM.md` rules 1-3.** This rule as
   written caused Ram's 2026-08-14 BUG-001/BUG-002. It specified strictness in
   one direction only (bulk must not be looser than the catalog) and was
   implemented literally as `_LEGACY_CATALOG_OPTIONAL_CATEGORIES`, which made
   bulk import *stricter* than the manual create path it was meant to match.
   With only 4 DRT entries in the production catalog for all of India, that
   gate made a Mumbai DRT matter unimportable while the identical payload
   created fine by hand. The single-master requirement stands; the
   fail-closed-by-default requirement does not.

   Original text, retained as history:

   > Any new hierarchy offered by both manual and bulk creation must have one
   > server-owned active master. Persist its ID and derived lineage, revalidate on
   > preview and commit, and reject ambiguous/invented values. If a historical
   > import contract needs a compatibility path, keep it explicit and narrower
   > than the new catalog-backed categories.
6. Never classify a release as fixed from source tests alone. Record commit,
   image/revision, migration, traffic, local build, local replay, production
   replay, cleanup, and final persisted state.
7. A concurrency-one UI must not make a supporting request race its primary
   action when the primary response contains the same facts. Production corpus
   counters must be constant-time (catalog estimates or materialized state),
   and interactive requests must not download/resolve tokenizers or models or
   initialize an ONNX session. Warm those assets before readiness and retain a
   process singleton.
8. Use Cloud Run service-level minimum capacity. Clear obsolete traffic tags on
   every canonical production deploy and verify only latest receives traffic;
   do not let tagged revisions preserve revision-level minimum instances or
   pinned, obsolete secret versions.
