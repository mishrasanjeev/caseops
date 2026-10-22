# Docker acceptance storage admission

`scripts/verify-docker.ps1` requires at least **64 GiB available bytes and
100,000 available inodes** on the actual Docker-backed filesystem. This is a
conservative headroom floor for production image export, eight native groups,
database/WAL growth and the complete browser fixtures, not a measured maximum
or a reservation against concurrent Docker users.

Admission runs before image build, after build before stack startup, before
native PostgreSQL, and before each browser invocation. The later probes also
measure the running acceptance project's own PostgreSQL volume. Insufficient,
missing, malformed or failed measurements, or incomplete probe cleanup, refuse
the next stage. Exact threshold values are accepted. There is no environment
override, pruning, Docker restart, retry or test skip.

The already-local API base `python:3.13-slim` must be present. The probe never
pulls an image: it resolves that image to an immutable ID, rejects unexpected
image volumes, and starts only its uniquely named, owner-labelled container.
That container has no network, a read-only root, dropped capabilities and no
new privileges. PostgreSQL volume inheritance is read-only and requires exact
Compose project/service/container/mount ownership. The only measurement is
Linux `os.statvfs`; Windows free space and aggregate `docker system df` are not
capacity evidence.

Each `docker-storage-<stage>-<nonce>.json` receipt records exact source release,
project, image, owned probe, byte/inode facts, bounded native command outcomes
and cleanup. A host command timeout kills/reaps its own Docker CLI; cleanup
rechecks the unique label and name before removing only that probe container.
Never interpret a refused admission as a product test result or resume/carry
an incomplete gate. The operator must resolve capacity separately, preserve
the failed receipts, and start a fresh canonical gate.

Offline regression coverage is in
`apps/api/tests/test_docker_storage_headroom_20261022.py` and
`tests/docker-storage-headroom-guard.ps1`. Fakes are in-process and cannot fall
through to a real Docker executable on a noexec temporary filesystem.
