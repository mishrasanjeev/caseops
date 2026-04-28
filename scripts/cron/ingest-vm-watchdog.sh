#!/usr/bin/env bash
# Ingest-VM watchdog — pure bash, no Claude / no LLM cost per run.
#
# Per user 2026-04-27 standing authorization:
#   "you should keep checking ingestor VM status every 1 hour and
#    resetting it , if its not working."
#
# What it does each invocation:
#   1. Probe https://api.caseops.ai/api/authorities/stats
#   2. If last_ingested_at is < 2 hours old: ingest healthy → exit 0.
#   3. If stale >= 2 hours AND VM SSH unreachable: reset + restart
#      sql_proxy + en_sweep + hc_sweep_all screens.
#   4. Append a one-line audit row to ~/.cache/caseops/ingest-watchdog.log
#
# Anti-loop: if a reset happened in the last hour (per the audit log),
# this run is a no-op so a stuck VM mid-boot doesn't get reset twice.
#
# Setup: GCP Cloud Run Job triggered by Cloud Scheduler.
# The wiring (SA, Secret Manager cookie, Cloud Run Job, Scheduler) is
# provisioned by scripts/cron/deploy-watchdog.sh. Run that script once
# per source change. The Job runs this bash file via the entrypoint
# wrapper at scripts/cron/entrypoint.sh (which dumps the per-run log
# to stdout for Cloud Logging).
#
# Manual fallback options (workstation cron) preserved at the bottom of
# scripts/cron/deploy-watchdog.sh comments — only relevant if the GCP
# Job is unavailable.
#
# Prereqs (whatever host runs it):
#   - gcloud CLI authenticated as a principal with
#     compute.instances.reset + compute.instances.get + compute.ssh
#   - python (3.10+) for cookie/JSON parsing
#   - The QA Bot session cookie file at $QA_COOKIE_FILE (default
#     tests/e2e/.auth/qa-storage.json — refresh hourly via the same
#     cron OR longer-lived service account auth)
#
# Exit codes: 0 = nothing to do or successful reset. Non-zero = a hard
# error worth surfacing (cookie file missing, gcloud auth failed).

set -uo pipefail

LOG=${WATCHDOG_LOG:-$HOME/.cache/caseops/ingest-watchdog.log}
ZONE=${INGEST_VM_ZONE:-asia-south1-c}
INSTANCE=${INGEST_VM_NAME:-caseops-ingest-vm}
PROJECT=${INGEST_VM_PROJECT:-perfect-period-305406}
STALE_HOURS=${INGEST_STALE_HOURS:-2}
ANTILOOP_MIN=${INGEST_ANTILOOP_MIN:-60}

mkdir -p "$(dirname "$LOG")"

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "$(stamp) $*" >> "$LOG"; }

# 1. Probe the live API. /api/health/ingest is unauthenticated and
#    returns global corpus aggregates (no tenant data). No cookie
#    refresh discipline required — durable signal. (Prior cookie path
#    abandoned on 2026-04-28 after a session of expiring-cookie noise.)
FALLTHROUGH=""
STATS=""
LAST_INGESTED=""
DOC_COUNT="?"
AGE_HOURS="?"

STATS=$(curl -sS -m 60 "https://api.caseops.ai/api/health/ingest" 2>/dev/null) || STATS=""
if [[ -z "$STATS" ]]; then
  FALLTHROUGH="api_unreachable"
else
  LAST_INGESTED=$(echo "$STATS" | python -c "import json,sys; print(json.load(sys.stdin).get('last_ingested_at',''))" 2>/dev/null)
  DOC_COUNT=$(echo "$STATS" | python -c "import json,sys; print(json.load(sys.stdin).get('document_count',0))" 2>/dev/null)
  if [[ -z "$LAST_INGESTED" || "$LAST_INGESTED" == "None" ]]; then
    FALLTHROUGH="no_last_ingested_at_field"
  fi
fi

# 2. Compute age + decide action.
#    The API probe is the SOLE authoritative signal. If it's not
#    available (cookies expired, file missing, etc.) we exit silent —
#    a stale signal could trigger a false-positive reset on a healthy
#    VM. SSH probes were tried as a fallback but failed in 2 distinct
#    ways on 2026-04-28 (Cloud Run → IAP key push timeouts; Workspace
#    org rejecting SA OS Login). Standing-auth manual reset still
#    works when the user spots a stuck VM.
if [[ -n "$FALLTHROUGH" ]]; then
  log "WARN api_signal=${FALLTHROUGH} — exiting without action (refresh tests/e2e/.auth/qa-storage.json + push to Secret Manager to restore signal)"
  exit 0
fi

AGE_HOURS=$(python -c "
from datetime import datetime, timezone
import sys
li = sys.argv[1].rstrip('Z')
try:
    t = datetime.fromisoformat(li).replace(tzinfo=timezone.utc) if 'T' in li else None
except Exception:
    t = None
if t is None:
    print('-1')
else:
    delta = datetime.now(timezone.utc) - t
    print(f'{delta.total_seconds() / 3600.0:.2f}')
" "$LAST_INGESTED")

if (( $(echo "$AGE_HOURS < $STALE_HOURS" | bc -l) )); then
  log "OK age=${AGE_HOURS}h doc_count=$DOC_COUNT — ingest healthy"
  exit 0
fi

# 4. Anti-loop check: did we reset within the last $ANTILOOP_MIN min?
RECENT_RESET=$(grep "ACTION reset" "$LOG" 2>/dev/null | tail -1 | awk '{print $1}')
if [[ -n "$RECENT_RESET" ]]; then
  RESET_AGE_MIN=$(python -c "
from datetime import datetime, timezone
import sys
t = datetime.fromisoformat(sys.argv[1].rstrip('Z')).replace(tzinfo=timezone.utc)
delta = datetime.now(timezone.utc) - t
print(f'{delta.total_seconds() / 60.0:.0f}')
" "$RECENT_RESET")
  if (( RESET_AGE_MIN < ANTILOOP_MIN )); then
    log "DEFER age=${AGE_HOURS}h doc_count=$DOC_COUNT — recent reset ${RESET_AGE_MIN}m ago, skipping"
    exit 0
  fi
fi

# 5. Reset. API confirmed last_ingested_at >= STALE_HOURS old — the
#    standing-auth directive is "reset if not working". No SSH probe
#    gate here (would be a false-positive minefield from this Cloud
#    Run container, see 2026-04-28 incident).
log "ACTION reset age=${AGE_HOURS}h doc_count=$DOC_COUNT"
gcloud compute instances reset "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --quiet >/dev/null 2>&1
RESET_RC=$?
if [[ $RESET_RC -ne 0 ]]; then
  log "ERROR reset_failed rc=$RESET_RC"
  exit 4
fi

# 7. Done. The VM's startup-script (scripts/vm/startup-script.sh,
#    installed via instance metadata) auto-launches the 3 screens
#    (sql_proxy + en_sweep + hc_sweep_all) on every boot. The watchdog
#    SA does not need OS Login as `mishra_sanjeev_gmail_com`, just the
#    ability to reset the instance. Trim done 2026-04-28 after the
#    OS-Login-as-SA false-positive incident.
log "OK reset_issued age_at_reset=${AGE_HOURS}h — startup-script will relaunch screens on boot"
exit 0
