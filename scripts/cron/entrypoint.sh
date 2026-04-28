#!/usr/bin/env bash
# Cloud Run Job entrypoint: runs the watchdog, then dumps the per-run
# log to stdout so Cloud Logging captures every OK/DEFER/ACTION line.
#
# Anti-loop in the watchdog reads $WATCHDOG_LOG to suppress
# back-to-back resets within ANTILOOP_MIN. In Cloud Run, the FS is
# ephemeral per execution so the anti-loop is per-run only — Cloud
# Scheduler's hourly cadence is the real anti-loop. That's intentional.

set -uo pipefail

: > "${WATCHDOG_LOG:-/tmp/watchdog.log}"
/opt/watchdog/ingest-vm-watchdog.sh
RC=$?
echo "=== ingest-vm-watchdog.sh exit=${RC} ==="
echo "=== watchdog log dump ==="
cat "${WATCHDOG_LOG:-/tmp/watchdog.log}" 2>/dev/null
exit "${RC}"
