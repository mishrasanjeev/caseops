# Scanner Timeout Fixture Boundary

## Observed CI Failure

E968 Security40945043009/job123698110247 has74passed native offline cases and
one error in test_real_client_timeout_removes_actual_owned_container. Its
one-second shared fixture budget expired during real Docker creation, before
an ID was acknowledged. Production cleanup correctly raised the stronger
unacknowledged-creation ScanError. This is not a secret finding or a broken
fail-closed fence. Keep the full failed log and native artifact.

## Narrow Correction

Only this known-created-container test gets a bounded10second setup-plus-start
fixture budget, consistent with neighboring real-container fixtures. Its real
attached-start client is explicitly capped at min(remaining_budget,1second).
The test requires the exact exception object captured inside REAL_RUN(start),
its exact command and <=1second timeout, the acknowledged ID, incomplete scan
evidence, confirmed cleanup and a real inspection proving owned-name absence.
An unknown create, synthesized pre-start timeout or substituted cleanup error
cannot satisfy it. Creation is neither preperformed nor falsely acknowledged.

No scanner/product/cleanup deadline, security policy, suppression, retry,
warmup or production behavior changed. Original pure shared-budget, exhausted-
create, malformed/lost-ack and cleanup-deadline controls remain unchanged.
The old assumption that this positive fixture could always create and attach
within one second is superseded; its one-second actual transport cap remains.

## Local Evidence And Remaining Gates

All75actual source-owned unittest identities pass in isolated local Linux
Docker, no skips/retries, incremental per-case results, exact ordered inventory
and unchanged source hashes. Execution uses a digest-pinned tools image and
network-none native/scanner containers; dependency preparation was separate.
Real fixtures use a new daemon-native volume so nested bind mounts refer to
the actual same bytes. Native container and attached client exit0; the owned
container/volume are removed after evidence export. No unrelated Docker data
was pruned or stopped. Actual reconciliation SHA256
ddf239ddae08e9d478aad8b26756718bbb8117d4542b20545242830909a256dd,
under Local/CaseOpsTestEvidence/portfolio-export-worker-20261026/
secret-scan-native-20261030-01.

Docker25 was explicitly interrupted before image builds so the corrected
candidate can receive a complete replacement gate. Its prelude/fixture/typecheck
prefix is not full regression acceptance. Require new committed hosted Security
including the actual tree/history scan, full canonical Docker, protected main,
guarded deployment and exact-release production certification. No App/native
store-release work or external hold is closed by this fixture correction.
