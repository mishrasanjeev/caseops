# IPLF-027B A0 production checkpoint - 15 August 2026

**Status:** partial A0 production evidence; release and acceptance are not
complete.

**Canonical control:** `docs/ip-implementation/PROGRAM_MANIFEST.yaml`

**Protocol carried forward:**
`docs/ip-implementation/evidence/m2/IPLF-027B/a0-quiescence-2026-08-14.md`

This checkpoint appends observed A0 rollout evidence without replacing the
original protocol or its earlier local/preparation history. It records the
exact default-off revision now serving, the successful first drain boundary,
and the gates that remain closed. It does not authorize or record Cloud Run
revision deletion, does not define `T_FENCE`, and does not implement or
authorize A1 or A2.

## Source and review lineage

Three focused pull requests reached canonical `main`. Each listed head passed
its complete CI, Security, and CodeQL workflows before merge:

| PR | Exact reviewed head | Canonical merge | Exact-head workflows |
|---|---|---|---|
| #227, schema-free A0 controls | `8ca87b97f19d7a27aee1e5e866d6718f3d58b46a` | `546644c4e3f1728a2296a5dddeece251b59ee491` | CI `31833296324`; Security `31833296422`; CodeQL `31833296237` |
| #228, terminal fingerprint polling | `55c3d69737a733fb2cf9f2d7c01a32b6cf00b1e9` | `d9bd3a042c21fa9c897c8028164514768a7445ff` | CI `31853929821`; Security `31853929783`; CodeQL `31853929805` |
| #229, newest fingerprint log page | `aef825d18d7de82d50bbf32e489f211c3cfa8c0b` | `6a78850100b5be0fddcf4278f42bcbc930e89d62` | CI `31862972492`; Security `31862972522`; CodeQL `31862972481` |

Canonical merge `6a78850100b5be0fddcf4278f42bcbc930e89d62`
also passed push CI `31864694113`, Security `31864694085`, and CodeQL
`31864693846`.

A later source-only security-hygiene change did not alter, rebuild, or redeploy
the A0 application:

| PR | Exact reviewed head | Canonical merge | Exact-head workflows |
|---|---|---|---|
| #230, reviewed Gitleaks history fingerprints | `b10d11ebaf3adf4df74d1d6da399369fb0a3e045` | `5154af359b5351224c34db7468eef5704d3d0faa` | CI `31868724166`; Security `31868724197`; CodeQL `31868724167` |

Thus `5154af359b5351224c34db7468eef5704d3d0faa` is the canonical source
checkpoint while the exact application release serving production remains
`6a78850100b5be0fddcf4278f42bcbc930e89d62`. The only intervening source
content is `.gitleaksignore`; no runtime artifact or service identity is
silently attributed to the later source commit.

Exact-main push CI `31871239153` passed all 16 jobs, including real PostgreSQL,
Ruff, web, all ten API shards, aggregate coverage, Playwright, and the main
staging gate. Security `31871239057` passed all six jobs subject to the zero-
commit Gitleaks limitation documented below; CodeQL `31871239066` passed all
three analyses. No scheduled event exists for this SHA.

The resulting main-push production workflow `31871239041` is truthfully
`failure`: its 1,500-second exact-release wait observed API/web still serving
`6a788501...` instead of source-only `5154af35...`, then skipped every
identity, QA, Playwright, A0-quiescence, and Notice step. This is neither a
production test pass nor an A0 behavior regression; it is the expected fail-
closed release-identity result of not redeploying a non-runtime
`.gitleaksignore` change.

The first two deployment attempts stopped fail closed before API routing:

- `546644c4...` built and migrated successfully, but the fingerprint wrapper
  treated a present `Completed=Unknown` condition as terminal and rejected the
  still-incomplete execution description. PR #228 corrected the polling gate.
- `d9bd3a04...` built and migrated successfully, but bounded log retrieval read
  the oldest page and did not find the canonical fingerprint line. PR #229
  corrected the log-order gate.

Both failures left production on predecessor API revision
`caseops-api-00293-nf2`; neither attempt created an A0 service revision or
routed traffic. These are preserved as fail-closed release-control results,
not successful deployment evidence.

## Exact deployed A0 identity

The final deployment used exact canonical merge
`6a78850100b5be0fddcf4278f42bcbc930e89d62`:

| Control | Observed result |
|---|---|
| API Cloud Build | `d1608381-6d1d-430d-aa71-1a47b1318eea`, success |
| API immutable image | `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:c5e6e687f6f37dc625711e4dbfa73a3766fa51e9b955c4bfb70da4faf7b3981c` |
| Web Cloud Build | `f9e19535-0349-415b-be06-b17e1da7913f`, success |
| Web immutable image | `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-web@sha256:e57ace5ed05015d4b4e02cfc5e85d59d3f1f7e874237edbcfd15e163c2f3581a` |
| Migration | `caseops-migrate-job-pf5jt`, successful on the exact API image; A0 remained schema-free at Alembic head `20260814_0001` |
| API service | `caseops-api-00294-x7w`, exact release and image, ready and untagged at 100% traffic, `CASEOPS_IP_RULE_GOVERNANCE_ENABLED=false` |
| Web service | `caseops-web-00272-dhf`, exact release and image, ready and untagged at 100% traffic |
| `T_ROUTE` | `2026-08-15T05:16:31.212471300Z`, defined only after exact service/revision/traffic convergence |

All six recurring Cloud Run Jobs were reconciled to the exact API digest. The
five intended schedulers were enabled, the authority-metadata scheduler and
superseded midnight poll remained paused, and the post-route scheduler audit
passed. The non-recurring `caseops-ip-qa-bootstrap` job was repinned to the
exact A0 digest without execution: its observed count remained five and its
latest execution remained the earlier successful
`caseops-ip-qa-bootstrap-6sv8v`. The temporary fingerprint job remained outside
recurring scheduler inventory.

## Fingerprint and first-drain proof

All three read-only PostgreSQL captures returned overall SHA-256
`07e68feb13e82fbedd42150df38904a10ce73a89b0348674de31833e7642673d`.
They also retained the same dataset counts in canonical order: one IP rule set,
one IP rule version, one company policy, and two governance audit events
(`1/1/1/2`). Content hashes, maximum timestamps, schema identity, and Alembic
heads were unchanged.

| Boundary | Exact fingerprint execution | Capture time | Result |
|---|---|---|---|
| final pre-route baseline | `caseops-ip-rule-governance-fingerprint-a0-44skf` | `2026-08-15T04:42:11.659680Z` | exact-image terminal success; baseline persisted before API routing |
| immediate post-route comparison | `caseops-ip-rule-governance-fingerprint-a0-c6jlr` | `2026-08-15T05:18:45.879328Z` | exact enforced equality |
| first-drain comparison | `caseops-ip-rule-governance-fingerprint-a0-58tkl` | `2026-08-15T05:23:33.976537Z` | exit 0 and exact enforced equality |

The fixed old-cohort log-audit cutoff was
`2026-08-15T05:22:32.212471300Z`, exactly 361 seconds after `T_ROUTE` (the
301-second minimum plus a 60-second coverage/drain margin). The logging query
ran more than three minutes after that fixed cutoff, providing the separate
ingestion-observation margin. A separate local
pre-fingerprint marker was written later at
`2026-08-15T05:23:18.8005322Z`, and the first-drain fingerprint itself was
captured at `2026-08-15T05:23:33.976537Z`. The request, stdout/stderr, and
error-log review covered only the fixed audit window through
`05:22:32.212471300Z`; it passed with no post-`T_ROUTE` rule-governance
completion or other unexplained old-cohort write evidence observed. This is
the first drain boundary only; it is not termination proof and cannot
substitute for deleting the approved cohort and proving absence.

## Exact production acceptance checkpoint

Production workflow `31864693967` checked out and targeted exact serving SHA
`6a78850100b5be0fddcf4278f42bcbc930e89d62`:

- the dedicated IPLF-027B A0 step passed its one dated test in 14.8 seconds,
  proving the three governance mutation paths fail closed and the bounded legal-
  deadline continuation journey remains operable against the exact serving
  revision;
- the Notice module step passed both tests in 17.1 seconds;
- the broader RAM batch recorded 69 passed, three failed, and four skipped.
  All three failures were recommendation/grounding calls returning the explicit
  provider-quota `503`; therefore the workflow conclusion is correctly
  `failure`. This checkpoint does not relabel the whole workflow green or use
  its unrelated successful tests as complete IPLF-027B acceptance.

Separately, scheduled Security run `31865741914` failed only its Gitleaks
history scan: Gitleaks `8.24.3` ran `detect --redact -v --exit-code=2
--report-format=sarif --report-path=results.sarif --log-level=debug`, scanned
1,036 commits / 45.33 MB, and reported nine `generic-api-key` findings. Review
proved those nine exact fingerprints were non-secret matter/fixture/control
identifiers and one already-public Cloud Build UUID. PR #230 added only those
exact history fingerprints to `.gitleaksignore`; it added no wildcard or path-
wide suppression and its exact-head Security workflow passed.

The official Gitleaks `8.24.3` Windows x64 archive was independently downloaded
with release checksum
`3f1a35578631dbfe633cc5b49e6c906e55ff14a4bfd7336a10fb27fe33b6dcd2`.
The extracted executable SHA-256 was
`8f397272f513c00b573f50380c4724e4b3ac759be1de313d907bb968c5d14c09`.
Using the same command against a clean exact-`5154af35` checkout containing
only current origin refs scanned the full history reachable from those refs:
1,041 commits / 39.77 MB, exit zero, and zero SARIF results. The 45,825-byte
local SARIF SHA-256 is
`f1cc1fc5bf34d5e9643655ac6480ff4681e27aa9c2c639f03067fc7ea8595e3d`.
This is operator-local parity evidence, not a GitHub scheduled-run conclusion.
Push Security run `31871239057` passed, but the action supplied
`--log-opts=--no-merges --first-parent b10d11e...^..5154af35...`; that option
and merge range yielded zero commits / approximately zero bytes. Its success
is therefore neither content nor history proof and must not be used as the
missing scheduled full-history result. A fresh scheduled full-history GitHub
pass remains required and is kept separate from the A0 runtime gate.

## Conditional pre-deletion packet

A read-only pre-deletion packet was captured and independently reviewed at
`C:\tmp\caseops-a0-6a78850100b5be0fddcf4278f42bcbc930e89d62\predelete`.
Its final fail-closed capture ran from
`2026-08-15T06:54:01.1526392Z` through
`2026-08-15T07:04:09.3415582Z`. The capture script SHA-256 is
`22ca391508ff69335d5effdafd2c64576dc85c479d1ad2bcdfd510cfc478adb9`;
the sealed `SHA256SUMS.txt` SHA-256 is
`11828e81ff62691d919e0cc1be0d79ba87598664355af8c81121f627bf50d21f`.
All 126 non-manifest entries across 127 total files verified, and all 110 JSON
files parsed.

The packet proves only its bounded snapshot: exact ready API revision
`caseops-api-00294-x7w` and web revision `caseops-web-00272-dhf`; API max
generation 294 with no newer revision; exact release/image/flag/single-traffic
topology; zero nonterminal executions under the strict terminal predicate;
capture of all 20 Cloud Run Jobs; material equality for the six canonical
recurring jobs, the QA-bootstrap job, the fingerprint job, and all nine
schedulers; six recurring-job IAM bindings; three equal governance
fingerprints; fixed-window old-cohort counts of 73 requests, 302 stdout
entries, 20 stderr entries, and zero errors; and zero post-`T_ROUTE` or
governance-writer entries. The other 12 captured jobs were not promoted to
material-equality holds. Its preview contains exactly 36 oldest-first deletion
commands for generations 258 through 293 and excludes protected generation
294. No preview command was executed.

The packet also records recovery limitations rather than hiding them. Only
three of 34 distinct legacy target images were still available; Artifact
Registry cleanup deletes unprotected images while keeping the latest five.
Cloud SQL was PostgreSQL 17 and runnable, but PITR was off, automated backup
retention was one, and deletion protection was off. Revision-object deletion
does not operate on Cloud SQL, images, builds, source, services, jobs,
schedulers, IAM, secrets, or logs, and all of those resources are excluded from
the preview. A deleted revision object has no undelete operation.

This packet is local, mutable, historical evidence and is not an approval or an
executable authorization. Canonical source subsequently advanced from the
deployed `6a788501...` release to source-only `5154af35...`; production did not
change. Before any deletion, an explicit owner decision plus a deployment and
operational-write freeze must be in force, and the complete fail-closed
capture, fixed-window log checks, preview validation, reseal, and independent
hash review must all be repeated. Any drift invalidates the earlier packet.

## Evidence provenance

The rollout operator evidence directory is
`C:\tmp\caseops-a0-6a78850100b5be0fddcf4278f42bcbc930e89d62`.
It contains the build, image, migration, service/revision, scheduler, execution,
fingerprint, and local cutoff-marker captures summarized above. The raw
request/stdout/stderr/error responses used for the original fixed-window
old-cohort review were not persisted in that directory at checkpoint authoring;
the exact filter, counts, and operator-observed result therefore remain a
disclosed limitation of the original rollout capture. The later sealed
pre-deletion subdirectory contains sanitized fixed-window captures and their
machine summary; raw unredacted log responses were processed in memory and
intentionally not persisted. Both paths remain local, mutable operator evidence
only; neither is a committed artifact, external run ID, or independently
immutable release archive. GitHub workflow IDs above are the external records
for their corresponding checks.

## Gates still closed

- The exact 36-revision writer-capable cohort has **not** been deleted. No
  irreversible deletion was approved or run. The sealed historical preview is
  not approval and must be replaced by a fresh frozen-window packet after an
  explicit decision.
- `T_FENCE` is undefined. Per-target `NOT_FOUND`, empty fresh-list
  intersection, successful Admin Activity deletion events, the at-fence
  fingerprint, the second 301-second-plus-ingestion drain, and its final
  fingerprint/log/job proof do not exist yet.
- The safe runtime state remains exact A0 with rule governance explicitly
  false. Do not route back to a pre-A0 writer-capable revision.
- A1 migration/backfill/reconciliation and all A1 authorization, evaluator,
  emergency-disable, and real-PostgreSQL concurrency gates remain unimplemented
  or unproved by this checkpoint.
- A2 is forbidden. There has been no config-only enablement and no authorized
  resumption of rule-governance writes.
- IPLF-027B remains exactly `implementation=in_progress`,
  `verification=not_run`, `release=blocked`, and `acceptance=pending`. This
  checkpoint is not release completion, milestone closure, or human sign-off.

The next destructive step may occur only after a separate owner decision on an
exact, freshly revalidated deletion preview and recovery packet. If approval is
given, delete only the named 36-revision allowlist oldest first, predecessor
last; prove all three absence/audit controls before defining `T_FENCE`; then
perform the second drain and enforced fingerprint comparison. Until every one
of those controls passes, keep A1 and A2 stopped.
