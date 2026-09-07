# Offline Docker Test Tools

The full API test image needs the locked development dependencies and the
Temporal SDK's real test server. Download free build dependencies before network
isolation. Runtime regressions remain network-disabled and use deterministic
providers; this does not authorize live paid requests.

On September 06 the SDK 1.27.2 server was already cached in the local test
image under `/tmp/temporal-test-server-sdk-python-1.27.2`. A clean exec-enabled
tmpfs hid that cache. The SDK attempted another download and the complete run
failed one notification workflow test. Do not skip the workflow or remove
network isolation to accept that run.

Build the tools layer from the prepared test image:

```powershell
docker build --build-arg CASEOPS_TEST_BASE_IMAGE=caseops-judgment-full-tests:20260905 -f scripts/docker-test-tools.Dockerfile -t caseops-offline-test-tools:20260906 .
```

The build may fetch the pinned free statute-compiler dependencies from PyPI.
Use `--network none` for a rebuild only when the prepared parent already has
that exact compiler environment. The test executions themselves remain
network-disabled; a connected dependency build is not a paid-provider test.

The layer verifies the exact binary hash and retains it outside `/tmp` at
`/opt/caseops-test-tools/temporal-test-server`. The current Linux amd64 binary
hash is `daa58458d32f6254a901085c27ad1c19a64a4e171679ed08b5b92c298baba6ce`.
This is a repeatability pin for the already downloaded artifact, not a claim of
independent vendor signature verification. A dependency/architecture change
requires a newly retrieved official SDK test server and an explicit new pin.
Never silently substitute another executable or bypass a mismatched digest.

Run this image with `--network none` and, when using tmpfs for the test clone,
`--tmpfs /tmp:rw,exec,size=3g`. The deployment-shell fixtures also require
executable storage; chmod cannot override a noexec mount. Keep the repo snapshot
read-only and write JUnit/log artifacts to the separate evidence mount.

The image now refuses implicit execution. Always supply `--entrypoint bash`,
the inspected current-source runner path and a unique `RUN_LABEL`. Do not rely
on an inherited `/usr/local/bin/run-full-tests.sh`: a base image can retain
another worktree's branch/index and generic output paths. The default-command
regression must fail before any snapshot or test starts; the explicit runner
must separately prove its source archive, selected identities and named JUnit.

`tests/test_durable_workflows.py` accepts both
`CASEOPS_TEST_TEMPORAL_SERVER_PATH` and `CASEOPS_TEST_TEMPORAL_SERVER_SHA256`.
The tools image configures them. A partial configuration, missing/non-executable
file, oversized file or incorrect hash fails before starting the SDK server.
Without either variable, ordinary connected developer tests retain the SDK's
existing download/cache behavior. The real workflow must pass with the explicit
binary inside the network-disabled container before accepting the offline setup.

The tools Dockerfile is test-only. It is not used to build or deploy the API,
web or worker production images.

## Replaying A Retained Browser Stack

The canonical fresh verifier resets its owned project. A focused or full replay
against `-KeepRunning` instead retains application state, including the web
process's five-request hourly public-demo bucket. Read each failure and trace
before classifying a 429. Do not disable anti-abuse controls, spoof a client IP,
increase timeouts, or retry a submitted mutation to make acceptance pass.

When that prior-run bucket is the proven blocker, verify the exact owned web
container, Compose project label and expected image digest, restart that web
container only, and record before/after container and image identities plus
start times. Wait for read-only release readiness, then replay the full browser
selection once with zero retries. Preserve the original failed report and every
database fixture; do not restart another user's stack or globally prune Docker.

Existing-QA production-shaped rehearsals must retain old fixtures too. Give
each new synthetic document unique content bytes, assert the upload outcome
before reading its document, and preserve duplicate-detection behavior. A
parallel read-only statute audit authenticates once per worker; a per-batch
login would amplify 43 data batches into 43 logins. Release identity checks,
the no-paid-provider marker and complete source-record assertions remain in
both local and production configurations.
