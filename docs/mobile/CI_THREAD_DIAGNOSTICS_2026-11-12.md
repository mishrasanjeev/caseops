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
