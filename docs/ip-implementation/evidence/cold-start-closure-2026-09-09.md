# Cold Start Closure Track - 2026-09-09

## Ownership And Lineage

- Owner: cold-start sidecar. Migration revision: none; no database migration.
- Worktree: `C:/Projects/CaseOps/caseops/.worktrees/codex-cold-start-closure-20260909`.
- Branch: `codex/cold-start-closure-20260909`.
- Baseline: `5145fb3a4b51b26af116220ff10a7389bde6324d`.
- D was read only: `C:/Projects/CaseOps/caseops/.worktrees/codex-sep08-acceptance-repair-20260908`.
- Exact `git ls-files -m -o --exclude-standard -z` snapshot: 67 files copied
  using bounded absolute destinations and `Copy-Item`; source-before,
  source-after and destination SHA-256 equality verified for every path.
  Inventory: `C:/tmp/caseops-cold-start-closure-20260909/source-copy-manifest.json`.
- The inherited dirty files are not this track's edits. No shared ledger,
  programme manifest, deployment script or infrastructure file is edited here.
- No commit, push, deployment, production mutation, or paid-provider call.

## Acceptance Mapping

Read the current unified PRD, IP programme manifest, September 08 bug evidence,
CODEX/AGENTS instructions, and the four required local skills before changes.

- J03/M02/US-006: authenticated portfolio availability.
- J04/M03/US-007/008, FT-011 through FT-015: document intake and retained reads.
- J05/M05: preserve native reranking and local-only model loading.
- J15/M15, NFT-001/004/005/009/012/016/017, EG-003: bounded readiness,
  observability, independent migrations, no egress, and real malware enforcement.
- IPLF-030A/B, IP-PORT-02/05, UJ-04-NORMAL: the existing portfolio owner;
  this track adds latency evidence, not a replacement portfolio implementation.

## Source Findings

The inherited candidate already removed an intermediate router clone and
overlapped scanner readiness with native warm-up. Those changes are preserved.
Existing image bytecode and local model caches are also preserved.

The scanner check had a 60-second deadline but native warm-up used
`asyncio.to_thread` without a deadline. A stuck initializer could prevent
readiness indefinitely, and cancelling that wrapper cannot bound the default
executor's shutdown. Startup now gives both checks one 60-second deadline and
uses one daemon initialization thread. An incomplete or failed check cannot
yield the lifespan; late completion cannot resolve a cancelled future.

The first actual portfolio request in the first diagnostic image cost 3.6644
seconds, versus 0.0592 seconds warm. The next candidate configures the canonical
in-memory SQLAlchemy mapper registry during readiness, before the native model.
No engine, connection, tenant query, database mutation, or migration is added to
that preparation. Phase timings name ORM, native, scanner and app construction.

## Verification Contract

`scripts/verify-api-cold-start.ps1` defaults to three independent serial runs.
Each uses a new PostgreSQL database, full migration chain, synthetic records
through canonical endpoints in a preparation-only process, a new API process,
and the pinned real ClamAV image. Timing starts before either serving container
is started. No production/shared database is cloned or read.

The first timed request is authenticated `/api/ip/portfolio?limit=100` and must
return the exact seeded application, asset, title, jurisdiction and phase. Only
pre-serving connection failures are polled; HTTP errors are not retried. Cold
response completion must be within 30 seconds. Three runs must each retain at
least three seconds of margin; a narrow pass does not certify stability.

Each run also proves warm portfolio within five seconds, native `fastembed`
readiness in the serving process, real clean upload and byte-identical download,
EICAR HTTP 400 with no extra attachment, scanner-outage HTTP 503 with no extra
attachment, unrelated health within five seconds, and successful upload/download
after restarting the same real scanner. Every request carries
`X-CaseOps-Automated-Test: no-paid-providers`.

Runtime bounds remain API 2 CPU/4 GiB, scanner 1 CPU/1500 MiB, PostgreSQL
1 CPU/1 GiB. Network: internal-only `10.254.239.0/24`, selected after inventory;
no published ports. Cleanup targets only this run's labelled containers/volume.
No scanner rule, signature database, timeout, or readiness fence is weakened.

## Evidence And Remaining Proof

Local implementation status: **Partially implemented** pending integrated
release/build/browser proof. The production 53.1926-second report remains
**Inconclusive** and release remains **NO-GO** until parent integration, fresh
release build, deployed identity and the dated production browser journey are
verified. No global programme or bug status is changed by this track.

### Repeated Real HTTP

Final local image:
`sha256:82f658701c088858d37e0dea054cc80f8443c780014cbe0b314c6577d98aa444`.
Evidence: `C:/tmp/caseops-cold-start-closure-20260909/repeat-02/result.json`.

| Fresh run | Cold portfolio, seconds | First HTTP, seconds | Warm HTTP, seconds | Post-outage health including exec, seconds |
| --- | ---: | ---: | ---: | ---: |
| 1 | 14.7709 | 0.1323 | 0.0337 | 0.6008 |
| 2 | 14.5174 | 0.1403 | 0.0362 | 0.5540 |
| 3 | 22.2118 | 0.2911 | 0.1104 | 0.6259 |

Exit code 0; three fresh databases/API/scanner containers; worst cold margin
7.7882 seconds. Every run has passing clean/EICAR, outage/no-attachment,
recovery/download and real native readiness evidence. API state proves exactly
2 CPU/4 GiB and no OOM kill for all three. The 49 retained run files occupy
375,852 bytes and contain no JWT-shaped session artifacts. Synthetic bearer
state lived only in a labelled disposable Docker volume.

The earlier diagnostic image
`sha256:b9cf9a4ee0d21f319c8d4639129fe52a82db2e01ebc31d0beb0307f7e6717bd9`
has three passing functional runs at 29.9259, 23.2859 and 21.1531 seconds, but
its worst margin fails the three-second stability requirement. Its invocation
exited 1; `repeat-01/result.json` remains `failed_stability`. September 08's
failed and narrow-pass evidence also remains unchanged.

These are cold processes/containers on the existing workstation, not fresh
host boots, uncached image pulls, production-scale tenant data, or Cloud Run
scale-from-zero proof. Host load and filesystem cache are not held constant;
do not attribute the entire wall-clock improvement to ORM warm-up. The
first-request initialization removal is independently supported by the
zero-SQL mapper regression and startup phase logs. The final image's first
run logs ORM preparation at 0.939 seconds before serving.

Exact image/source validation reconciles 686 application, migration and
dependency files against both `/app` and the installed package. Manifest:
`C:/tmp/caseops-cold-start-closure-20260909/image-source-proof-02.json`.
Combined source SHA-256:
`0b3e6cb5c6c70f77d8133a5a12832aef5efac7dc5020d4130af2e8f5129d9acc`.

The first attempt to build `apps/api/Dockerfile` with `--network none` failed
at its uncached Debian package layer (apt exit 100, DNS unavailable). This is
an offline build infrastructure failure, not successful release-build evidence.
The fallback test image overlays this exact worktree's source, installed package
and migrations onto runtime image
`sha256:e3cb3487fe3be42e179c42c542046774b928c6912eedd140ea58c6f5ac060305`.
Base and source dependency files match exactly:

- `pyproject.toml`: `29f53960d7af465a62604ab5484153688442a3693cee25f98f7cd3ea9c24b629`.
- `uv.lock`: `42d0f3be5745b25ad7c43c014fd79d6ac2f387bed680c593268b52363d1f5ff4`.

The fallback is labelled uncommitted and is not a production release image.
Build recipe and logs are under `C:/tmp/caseops-cold-start-closure-20260909/`.

### Focused Regression Reconciliation

The first focused Docker run completed with 41 passes and one synchronization
test failure. Its full setup/call/teardown journal and JUnit are retained as
`focused-01.jsonl` and `api-focused-01.xml`. The single failed test was
`test_lifespan_does_not_yield_before_both_readiness_checks`: its unchanged
one-second native-start signal deadline also measured 1.196 seconds of newly
added real mapper setup. The replacement isolates that unrelated mapper work
in the synchronization test, without increasing its deadline. Separate tests
still run the actual complete mapper graph and reject any SQL.

The native-model integration ran, not skipped, with networking disabled.
The replacement run passed all 54 tests (zero skips) in 82.96 seconds, exit 0.
`focused-reconciliation.json` verifies all 42 previous identities occur in the
replacement, every new identity has passing setup/call/teardown (162 reports),
the JUnit count is 54, and the journal has an exit-0 completion event. Artifacts:
`focused-02.jsonl`, `api-focused-02.xml`, and `focused-reconciliation.json`.
No failed evidence was overwritten. Selected modules: `test_startup_readiness`,
`test_cold_start_harness`, `test_reranker`, and `test_deploy_image_pinning`.
Python source Ruff and PowerShell parse checks pass. Baseline and candidate
serialized OpenAPI bytes match exactly, SHA-256
`9330636ea7ca7ef904763a9df2e60eb88006b8427935c8be84ade3cccd5cb42c`,
742 paths and 844 operations. See `openapi-comparison-02.json`; the first comparison's
PowerShell path-count serialization was malformed and is retained separately.
The initial read-only Ruff invocation failed to create its cache; the unchanged
check passes with `--no-cache`. No application change or gate waiver was used.

The offline test runner uses executable disk-backed scratch (more than 2 GiB
available), one pytest worker inside 2 CPU/4 GiB, and the supplied test-tools
image with `--entrypoint bash`. Its real Temporal binary remains pinned at
`/opt/caseops-test-tools/temporal-test-server`, SHA-256
`daa58458d32f6254a901085c27ad1c19a64a4e171679ed08b5b92c298baba6ce`;
no Temporal tests are claimed as part of this focused selection.

Eight additional deployment-policy cases pass in 37.95 seconds, exit 0:
service-level minimums/tag retirement, startup-dependency removal with four
existing metadata shapes, and rejection of three malformed metadata shapes.
All 24 phase reports reconcile with a completion event in `deploy-01.jsonl`;
see `api-deploy-01.xml` and `deploy-reconciliation.json`. This selection used
1 CPU/4 GiB with networking disabled. It is static/offline CLI regression
proof, not an assertion about current production configuration.

After the parent requested a coordinated final window, this track held all
further cold-stack launches. The completed `repeat-02` measurements preceded
that request. No CPU-contention cause is asserted from the observed variance.

## Integration Boundaries

Apply only this track's incremental hunks relative to the 67-file D snapshot:

- `apps/api/src/caseops_api/core/startup.py`: readiness coordinator, bounded
  native initialization, ORM warm-up and named phase timings.
- `apps/api/src/caseops_api/main.py`: warm-runtime callback, readiness call,
  construction timing; no route registration, middleware or schema changes.
- `apps/api/tests/test_startup_readiness.py`: coordinator monkeypatch target
  plus timeout, failed process exit, error and zero-SQL mapper regressions.
- `apps/api/tests/test_cold_start_harness.py`: new exact-record and gate tests.
- `scripts/cold-upload-http.py` and `scripts/verify-api-cold-start.ps1`: original
  portfolio, repeat/margin, retained failure and isolated fixture evidence.
- This dedicated evidence document.

Do not copy the inherited models, router, provider, statute data, manifest or
shared ledger files wholesale from this worktree.

Exact five-file incremental diffs are retained under
`C:/tmp/caseops-cold-start-closure-20260909/*.patch`. Shared `main.py` hunks:
remove `asyncio` import, replace the readiness import, add `warm_runtime`, call
the readiness coordinator in `lifespan`, and time application construction.
`core/startup.py` adds imports and the three helpers before `_ping_scanner`;
the existing scanner protocol/poll/deadline functions are unchanged. D's five
corresponding file hashes still matched the original copy manifest when these
diffs were produced.

Parent-owned deployment review: retain existing service-level API minimum
capacity, `--min-instances default`, obsolete-tag removal, latest-only traffic,
current secret versions and parallel API/scanner startup. Do not increase
timeouts or use revision-pinned warm instances to mask the remaining variance.
No additional deployment hunk has been executed or approved by this track.
