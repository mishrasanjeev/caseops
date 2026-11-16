# PostgreSQL timed diagnostics — 2026-11-12

J20/M22 release verification remains **Inconclusive**, release **NO-GO**. This
change has no native mobile case credit and is not a claim that the whole CI
run or either store release is complete.

## Failed CI and retained control

On PR head 300b7c0f19583270f8417020c80376d661272e38, CI run 43265906185,
job 131349479738 (PostgreSQL shard 9/32), the child exited on SIGSEGV (-11),
reported as exit 139. Its 127-case selected inventory retains 67 fully passing
cases and setup for the next case, the fresh-statistics retained-width export
projection. The timed native dump printed two SQLAlchemy frames and stopped;
there is no completed JUnit or successful session end. No remaining case is
counted as passed. Artifact 13969165299 is byte-verified at SHA-256
b4d69cd7ed862cc37aa2b8ea1e889362bae862ca2727e936a6757d677c8c7145.
Raw inventory, 202 passing phase reports, native signal/runtime receipt and the
failed dump remain in `ci-300b-postgres-shard09-artifact` and the retained job log.

Earlier c8dd job 131267211185 passed the complete same-sized shard on CPython
3.13.18. Its 60-second dump completed during normal retained import work, then
all 127 selected cases passed in 413.71 seconds. This is a separate control,
not acceptance for the failed 300b run. Both used CPython 3.13.18; no Python
version regression is asserted. No core backtrace was obtained, so the precise
crash cause remains Inconclusive. SQLAlchemy appearing in a sampled frame does
not prove an application hang or a SQLAlchemy defect.

CPython maintainers document unsafe live-thread frame sampling in
[issue 116008](https://github.com/python/cpython/issues/116008). That provides a
mechanism to avoid, not proof that this CI crash has that exact cause.

## Diagnostic change

The PostgreSQL workflow replaces the native background timed stack walk with
an explicit Python observer at the same 60 seconds. It obtains strong frame
references while the GIL is held and retains bounded code locations only: no
locals, source lines, credentials, HTTP bodies or query values. One exclusive
JSONL per case hash goes directly beneath the existing uploaded native evidence
root. Unknown publication or cleanup cannot silently pass. Original hook
exceptions remain original when diagnostic cleanup also fails.

Fatal-signal faulthandler remains enabled. Actual SIGSEGV, application failures,
reporter failure and missing native exits still fail. No test is retried,
removed, skipped or weakened, no GC behavior is changed, and the job remains
12 minutes with the same 32 shards/four concurrent jobs. All original artifact
paths and complete collection/JUnit/native-exit reconciliation remain. The
workflow's independent source guard checks the new exact observer arguments,
original 60-second observation point, and unchanged budgets and upload inventory.

The actual launcher fixture now carries the new plugin into its isolated child
source closure and supplies each child's correct uploaded evidence root. It
still executes all 32 child shards and all 64 synthetic marked identities with
normal pytest, without inherited application PYTHONPATH.

## Actual verification and limits

A fresh immutable snapshot binds base db3a094061dd093d32bffd4f24d295016ec3f3ac
and the four exact candidate files. API runtime code is unchanged from the
retained c8dd image. A separate Linux CPython 3.13.18 worker uses a private
throwaway venv containing descriptor-verified pytest 9.0.3, pluggy 1.6.0 and
iniconfig 2.3.0, with the pinned API image's existing runtime dependencies. Its
owned temporary filesystem permits the fixture executables to run; it has no
external network or provider keys.

Before pytest, a separate zero-case-credit qualification actually waited
60.009686 seconds while another Python thread constructed SQL expressions.
The observer captured that worker, published its bounded trace, joined both
threads, and independently confirmed fatal faulthandler was still enabled.
It performed no database write.

The complete affected inventory then passed all 441 phases, JUnit identities
and native child exit 0, without skips or timeout:

- test_postgres_thread_diagnostics.py: 12 cases.
- test_postgres_sharding.py: 126 cases, including the actual 32-child launcher.
- test_ip_portfolio_export_projection_20261026.py: 9 cases, including both fresh
  and analyzed retained-width journeys and unchanged physical-work/10s bounds.

The entire worker, including the physical qualification, finished in 229.868
seconds under the unchanged 720-second total. All fixture/source databases were
removed and absence verified; original database names/server identity remained.
Independent proof is in `ci-pg09-diagnostics-native-07/reconciled-proof.json`
under the task cache, with exact snapshot hashes, native journal/JUnit/exit and
physical diagnostic evidence.

Earlier stopped candidates remain: a capacity refusal before database creation;
a configuration-type refusal before pytest execution; and a full 147-case run
with 140 passes/seven fixture failures on a noexec temp mount and an interpreter
without locally installed pytest. Those failures were corrected in the test
runtime/source closure and the whole inventory repeated. None is relabeled a
passed full run. New hosted CI remains required before release sign-off.


## 2026-11-13 — diagnostic review follow-up

The ea68f74b hosted native PostgreSQL shard 9 passed. CodeQL separately reported
845 (unused frame assignment) and 846 (a swallowed BaseException in the observer
thread); a successful analysis workflow does not clear those alert verdicts.
The observer now deletes its held loop-frame reference explicitly. Ordinary
publication exceptions are retained; SystemExit/KeyboardInterrupt propagate to
the normal thread exception hook and are retained through sys.exception() in
finally so close still fails. Both original exception identities and actual
thread propagation are regressed. The original hook/cleanup preservation logic,
60-second threshold, fatal-signal handler and all workflow budgets remain.

The complete diagnostic and launcher modules passed 140 host cases with pinned
CPython 3.13.17 and an isolated pytest environment, including every actual child
shard invocation. A preceding run retained three failures caused by this Mac's
PATH omitting the installed GNU sha256sum; the unchanged complete selection was
replayed with its real Homebrew GNU binary. This is host control evidence, not
new PostgreSQL or Android/iOS acceptance. Fresh hosted analysis and independent
alert verdicts remain required; the original native crash root cause remains
Inconclusive without a core backtrace.

## 2026-11-16 — PR621 integration and Windows controls

Main `736c15d3fa742411207633b05517645348cca78c` (PR612) is integrated
locally into PR621. Both branches' tests, the safe timed observer, fatal
faulthandler, all32 PostgreSQL shards and original bounds remain. The original
hosted crash remains **Inconclusive**; fresh complete CI is required.

The complete Windows diagnostic/launcher selection collected140 cases:
137passed/3failed. Windows text-mode `os.open` translated the JSONL newline;
the noncanonical-root fixture required unavailable symlink privileges.
Explicit binary output now has an independent literal LF-byte assertion.
Windows exercises a real directory junction for the same root refusal; POSIX
retains a real symlink. The complete replacement passed140cases with zero
failures/skips in335.30seconds, native exit0 (`b5-diagnostics-sharding-02.xml`).

Actual Windows helper admission reproduced different pathname/descriptor ctime
values with identical positive creation times. Shared helper loaders, private
metadata comparisons and the gateway constructor now compare their shared
creation identity while retaining each channel's complete before/after checks.
Six native Windows controls pass, including actual same-byte pathname replacement
while the original descriptor stays open, zero execution on rejection, changed
creation identity refusal and descriptor closure.

The complete mobile helper module is declared for Ubuntu in CI. The retained
Windows whole-module attempt has49failures/7errors/5declared skips across126
cases, including POSIX mode/symlink assumptions. It is not Linux acceptance.
Complete Linux, hosted CI, browser, canonical Docker and deployed workflow proof
remain pending. Evidence: `C:/Users/mishr/.codex/merge161001`. **NO-GO**.

The complete offline Linux helper attempt executed126methods and retained three
subcase errors in the unchanged five-second Node readiness constructor probe.
All gateway, private-file, TLS and replacement methods passed in that attempt;
the whole module remains unsuccessful. The Windows gateway-consumer attempt
passed60/61 cases; its real symlink negative fixture requires the CI Linux
platform and is not replaced by a fake or permission waiver.

Fresh hosted source0d87d2c9 then reported six gateway-adapter failures:
1889passes/6failures/3declared skips in its1898-case harness inventory. The
adapter correctly refused the changed gateway's previous reviewed fingerprint.
Reconcile only its reviewed constant to the exact gateway bytes; keep the
implementation/tamper/snapshot binding and all six original negative controls.
Complete source gates must be repeated for that corrected candidate; the prior
failed run and unreached Python/browser boundaries remain retained.
