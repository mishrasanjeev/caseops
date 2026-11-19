# PR624: bounded native source collection on Windows

**Partially fixed / NO-GO.** Platform journey QG-REL-003/005/008: complete
frontend and browser inventories must run within their existing bounds. The
same source can pass locally and fail on a different release host; neither
result erases the other.

Hosted Windows CI44307961816, job134814523691, on cb734abf retains a failed
suite in `lib/prod-tester-source-inventory.test.ts`. Its native Playwright
`--list --config=playwright.app.config.ts --reporter=json` constructor exceeded
the original15-second limit in the complete App inventory's beforeAll hook.
All seven tests depending on that hook were unexecuted. The complete native
report has3201 passes, seven skips and one failed suite across313 files.
Local frozen frontend13 on the same commit has3208 passes across313 files,
zero failure/skip/todo and successful component compilation. This local pass
does not close the source-identical hosted failure.

The original configuration admits two coverage workers while the inventory
worker launches another cold Node/Playwright collector. Resource contention is
the working diagnosis, not a proven historical profile of the timed-out child.
The repair gives the complete source-inventory file an exclusive first project
group, then runs every other existing frontend file in the ordinary two-worker
group. Both projects explicitly inherit the existing configuration, trusted
fork pool, setup, aliases and React plugin. Coverage remains one native run.
Default exclusions are retained, and exactly one named file moves between the
two groups. No browser case, project, role, assertion or deadline is removed.

The implementation follows Vitest's supported ordered-project mechanism:
[parallel and sequential test files](https://vitest.dev/guide/recipes/parallel-sequential.html).
The installed and hash-reviewed Vitest4.1.12 implements groupOrder. Explicit
`extends: true` is retained for that version; newer documentation's default
inheritance must not be assumed for an older installed runtime.

The App collector still has15 seconds, production collection eight seconds,
and its existing hooks/units20 seconds. The complete App union stays792:
774 original identities, ten B5, six Nov14 and two Nov15. No prewarming,
cached inventory, retry or alternate expected result is introduced. Two new
negative controls require both a timeout and a nonzero native exit to reject
even valid inventory JSON, after exactly one constructor invocation.
The complete frontend expectation therefore becomes3210 cases across313 files;
the source-inventory file becomes51 cases, with the other312 files unchanged.

Required before acceptance: actual component compilation; real grouped native
execution with full identity equality against the prior3208 plus the two new
controls; native timing evidence that the inventory group finishes before any
ordinary test module starts; complete fresh hosted Windows and Linux coverage;
all affected source checks and unchanged cross-language deadline inventory.
Then complete exact-head CI, separate CodeQL and independent re-review, fresh
Docker acceptance, main checks, deployment and exact-serving production QA.
All earlier failed or incomplete native reports remain retained.

This change has no application, API, dependency, archive, SDK, licence or
production admission-policy change. All17 protected source/artifact inputs
must remain byte-identical to cb734abf. No expensive Docker06 was started for
the rejected candidate. Production remains acff and projection stays paused.

The first development project layout retained the broad include at the root.
Vitest4.1.12 merges inherited include arrays: actual native file discovery
therefore found313 files in the supposedly exclusive project plus312 ordinary
files (625 entries). The development full-list probe exceeded its300-second
outer budget without a native result. Its incomplete receipt is retained;
the exact owned parent and worker are independently absent. No product test
pass is inferred from that refused layout. Moving the unchanged broad include
into the ordinary project yields exactly313 unique native files, partitioned
one plus312, without duplicates. Actual component compilation then passes,
and the complete source-inventory file passes all51 cases without skips.
These are development results, not replacement full-suite or hosted proof.

A further native53-case integration passes every case, but its independent
timing check correctly refuses the claimed first-group order. The installed
Vitest4.1.12 scheduler appends isolated single-worker files with order0 after
the numbered groups. Source and component case ranges were disjoint but
reversed. The corrected layout uses positive orders1 and2, retaining the
single-worker source group and ordinary two-worker group. A fresh native
integration and timing/identity check must pass; case success alone does not
prove the intended group order. The original refused timing proof is retained.

The complete replacement53-case integration now passes, and its independent
timing guard passes with source case execution ending before the component's
first case starts. The original49 source-case identities are byte-for-byte
equal as structured title/tag identities, plus exactly the two new controls.
Fresh native file discovery retains the same313 file identities as the prior
complete frontend, partitioned exactly1+312 without duplication. All17
protected runtime/artifact inputs and original constructor/hook limits remain
unchanged. This integration used an already exercised development temp root;
it is not fresh-host cold timing proof. Full frozen frontend14 must use a new
private temp/cache root, then complete fresh hosted Windows/Linux acceptance.
