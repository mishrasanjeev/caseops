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
# Setup options (pick ONE):
#
# A) GCP Cloud Scheduler (recommended — fully GCP-side, no workstation):
#      gcloud scheduler jobs create http caseops-ingest-watchdog \
#        --location=asia-south1 \
#        --schedule="7 * * * *" \
#        --uri="<HTTP endpoint that runs this script>" ...
#    OR adapt the script to a Cloud Function entrypoint + invoke from
#    Scheduler. Requires a SA with compute.instanceAdmin.v1 role.
#
# B) Windows Task Scheduler (this workstation):
#      schtasks /Create /TN "CaseOps Ingest Watchdog" \
#        /TR "C:\Program Files\Git\bin\bash.exe -c '/c/Users/mishr/caseops/scripts/cron/ingest-vm-watchdog.sh'" \
#        /SC HOURLY /MO 1 /ST 00:07
#
# C) cron / launchd (Linux/macOS workstation):
#      crontab -l | { cat; echo "7 * * * * /path/to/scripts/cron/ingest-vm-watchdog.sh"; } | crontab -
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
QA_COOKIE_FILE=${QA_COOKIE_FILE:-/c/Users/mishr/caseops/tests/e2e/.auth/qa-storage.json}
ZONE=${INGEST_VM_ZONE:-asia-south1-c}
INSTANCE=${INGEST_VM_NAME:-caseops-ingest-vm}
PROJECT=${INGEST_VM_PROJECT:-perfect-period-305406}
STALE_HOURS=${INGEST_STALE_HOURS:-2}
ANTILOOP_MIN=${INGEST_ANTILOOP_MIN:-60}

mkdir -p "$(dirname "$LOG")"

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "$(stamp) $*" >> "$LOG"; }

if [[ ! -f "$QA_COOKIE_FILE" ]]; then
  log "ERROR cookie_file_missing path=$QA_COOKIE_FILE"
  exit 2
fi

# 1. Probe the live API.
COOKIES=$(python -c "import json; d=json.load(open(r'$QA_COOKIE_FILE')); print('; '.join(f\"{c['name']}={c['value']}\" for c in d['cookies']))" 2>/dev/null) || {
  log "ERROR cookie_parse_failed"
  exit 3
}

STATS=$(curl -sS -m 15 "https://api.caseops.ai/api/authorities/stats" \
        -H "Cookie: $COOKIES" 2>/dev/null) || STATS=""
if [[ -z "$STATS" ]]; then
  log "WARN api_stats_unreachable — skipping (no signal to act on)"
  exit 0
fi

LAST_INGESTED=$(echo "$STATS" | python -c "import json,sys; print(json.load(sys.stdin).get('last_ingested_at',''))" 2>/dev/null)
DOC_COUNT=$(echo "$STATS" | python -c "import json,sys; print(json.load(sys.stdin).get('document_count',0))" 2>/dev/null)
if [[ -z "$LAST_INGESTED" ]]; then
  log "WARN no_last_ingested_at_field — skipping"
  exit 0
fi

# 2. Compute age.
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

# 3. Healthy → exit.
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

# 5. Confirm VM is unreachable (don't reset a healthy VM whose ingest
#    is just slow). 10s SSH probe.
if gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" \
     --command="echo READY" --quiet 2>/dev/null | grep -q READY; then
  log "DEFER age=${AGE_HOURS}h doc_count=$DOC_COUNT — SSH OK, screens may be in long phase"
  exit 0
fi

# 6. Reset.
log "ACTION reset age=${AGE_HOURS}h doc_count=$DOC_COUNT"
gcloud compute instances reset "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --quiet >/dev/null 2>&1
RESET_RC=$?
if [[ $RESET_RC -ne 0 ]]; then
  log "ERROR reset_failed rc=$RESET_RC"
  exit 4
fi

# 7. Wait for SSH (max 5 min).
DEADLINE=$(( $(date +%s) + 300 ))
while (( $(date +%s) < DEADLINE )); do
  if gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" \
       --command="echo READY" --quiet 2>/dev/null | grep -q READY; then
    break
  fi
  sleep 8
done

# 8. Restart 3 screens (sql_proxy + en_sweep + hc_sweep_all).
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --project="$PROJECT" --quiet --command='
  screen -dmS sql_proxy bash -c "cloud-sql-proxy --port 5432 perfect-period-305406:asia-south1:caseops-db; exec bash"
  sleep 6
  ss -lnt | grep -q ":5432" || echo "WARN proxy_not_listening"
  screen -dmS en_sweep bash -c "cd ~ && ~/run_sweep_en.sh; exec bash"
  screen -dmS hc_sweep_all bash -c "cd ~ && ~/run_sweep_hc_all.sh; exec bash"
  sleep 4
  screen -ls
' >/dev/null 2>&1

log "OK reset_complete age_at_reset=${AGE_HOURS}h"
exit 0
