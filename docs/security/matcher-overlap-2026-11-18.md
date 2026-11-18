# PR624: preserve repeated-alternative safety

Status at repair development: **Partially fixed; NO-GO**. This is not deployed
acceptance. Module/platform gate: QG-SEC-001. User story: an untrusted pattern
must not freeze a web, mobile or installer process, including patterns the
original matcher already refused safely.

The configured GitHub Codex reviewer reported P1 comment4613399770 against
25ab314688967a887368fb53902f7b74aace9a59. The private backport replaced the
old same-character overlap check with a divisibility check. Two does not divide
three, so `+(aa|aaa)z` stopped being literalized and could backtrack indefinitely.
Clean dependency audits and CodeQL analyses did not prove this runtime boundary.

The retained native control reaches both `ready` and `matching`. The pinned
original returns false immediately for100 `a` characters followed by `!`;
the rejected backport exceeds the unchanged1000ms matching budget. Node24
also reproduces the adjacent `abab|ababab` case. Preparation retains the
existing20-second bound and inherited trust setup. A cold-start refusal is not
counted as an entered matcher. These red reports are retained separately from
the earlier bracket-removal and glob-star witnesses.

The repair keeps the original same-character check and recognizes nonempty
words that commute (`a + b === b + a`), which are repetitions of a common word.
This covers non-divisible repeated words as well as the earlier divisible
example `ab|abab`. Empty alternatives stay outside this new check. Both orders,
a different repeated character, the star form and the literalized positive
path are covered. Existing ordinary, escaped, quoted, class, nested and trusted
opt-out controls remain. This is not a general promise about arbitrary regexes.

Current development proof in the operator's merge161001 evidence directory:

- `pr624-overlap-red22-01.log`: pinned-original immediate completion and
  rejected-backport acknowledged match entry followed by the original1s refusal.
- `pr624-overlap-red24-01.log`: two entered failures, including the adjacent
  non-divisible repeated-word witness. These are expected red controls.
- `pr624-overlap-focused-green22-01.log` and `-green24-01.log`: both focused
  cases pass naturally after repair on their actual accepted runtimes.
- `pr624-overlap-security2201.log` and `-security2401.log`: all seven complete
  security cases pass on each runtime, including original negative controls and
  the299593 finite backslash-output comparisons. No skips or retries.
- `pr624-overlap-producer01.log`: all12 deterministic origin, unchanged-byte,
  archive and publication controls pass. The canonical offline producer also
  verifies both generated output trees through real descriptors.

The proposed private version remains4.0.7-caseops.1; this first release has
not shipped. Its new archive is26417 bytes, SHA256
`0baf6afb8b049047c17d5312261705c6e26f018e7104133a0f4b8928444a8d57`.
The npm dependency rebundle is4067054 bytes, SHA256
`f106297722b91e631bdfe4de9776d3ed1d901764e9371d2f5aa7e506cd22111b`.
Its tar still has2154 members and17725440 bytes. Original MIT/attribution
bytes, official Arborist9.9.3 and all unrelated native SDK identities remain.
Both application locks change only the matcher integrity value. The mobile
lock stays266715 canonical LF bytes, with SHA256
`bcabce86da5bed3cb9c17e2868f1f4844bc3f48005fc86ff9a4845d1b799e346`.
The held iOS catalogue keeps its four packages, ten official archives and exact
producer, while rebinding the lock hash. Launchers and npm helper pins follow
the actual new bytes. The paired POSIX read-byte expectation is32065428;
actual Linux execution remains required before acceptance.

Docker05 was stopped after this independent finding. Its first526 PostgreSQL
cases completed all1578 phases naturally; group2 has276 passing bodies but
is interrupted. Groups3-8 and all792 local browser cases are unexecuted.
The canonical cleanup parent was retained. Exact-project containers, volumes
and networks are independently absent. All44 interrupted runtime files and
the original owned runtime remain retained. Auxiliary retention-reader
refusals are separate from product failures. Hosted CI was operator-cancelled;
its completed mobile63P/1S and other completed jobs remain scoped evidence,
not a passing whole workflow. No passing prefix transfers to the repair.

Still required: reconcile every locked/installed copy and every upload/image/
source/notice inventory; fresh platform audits; complete intended source and
SDK checks; actual web/component/E2E/mobile compilation; frozen full frontend;
new exact-head CI and independent review; complete replacement Docker inventory;
combined-main checks; canonical exact-SHA deployment; complete new production QA.
The original Batch5 production findings remain open until exact-serving replay.
Only successful mutation-capable QA followed by two later clean serial
projection executions, second rebuild_count0, admits guarded scheduler resume.
Production remains acff and projection remains paused.

Further development verification on the repair checkout: root and mobile
installation and frozen all-extras API installation completed before tests.
Both actual installed matcher inventories pass all ten native cases on Node
22.23.4 and 24.15.0, without failure, cancellation, skip or retry. All ten
serialized tooling checks completed: matcher, installer, build configuration,
licence, actual web upload closure, both installed graphs and fresh JavaScript
audits (zero vulnerabilities at every severity). Web component, E2E and mobile
compilation, API Ruff and all-extras dependency compatibility, governance map
and compiled projection validation also pass. These uncommitted development
checks do not replace the pending frozen release and production inventories.

The isolated security file has seven cases; the installed-copy file has three,
for ten combined cases. The earlier eight-case description was a counting
error, corrected against the retained native reports and literal declarations.

The first repaired-head CI (f80d2eb2) retains a separate mobile harness failure:
1909 declared cases, 1905 passed, one failed and three skipped. The accepted
current lock was read correctly, but a generated stale-node-forge variant now
contained the repaired matcher integrity and therefore differed from the
previous exact stale-lock digest. Both current-stale and historical bytes are
independently reconstructed on Node22 and Node24. The repair preserves the
historical 53c67dc3 digest and adds the current-stale 34022fda digest. Both must
be rejected before any archive payload is opened, with original positive
archive, wrong-extent and no-output assertions retained. Complete Linux native
harness replay and all later source/export steps remain required. No archive,
SDK, dependency, attribution or production-admission policy changes here.
