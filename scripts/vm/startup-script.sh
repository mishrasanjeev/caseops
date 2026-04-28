#!/bin/bash
# caseops-ingest-vm boot-time startup script.
#
# Installed via:
#   gcloud compute instances add-metadata caseops-ingest-vm \
#     --zone=asia-south1-c \
#     --metadata-from-file startup-script=scripts/vm/startup-script.sh
#
# Runs as root on every boot (manual reset, GCP maintenance event,
# rare Spot preemption recovery). Re-launches the 3 screens (sql_proxy,
# en_sweep, hc_sweep_all) under the developer user so the Phase-1
# watchdog only needs to call instances.reset() — no SSH-based screen
# restart required.
#
# Per project_canonical_deploy_script + feedback_ingestor_vm_hourly_watchdog:
# this is the foundational durability fix. The Cloud Scheduler watchdog
# (Phase 2) becomes a thin probe-and-reset.
#
# Idempotent: skips if the screen is already running. Logs to syslog.
set -uo pipefail
exec > >(logger -t caseops-startup) 2>&1
echo "startup-script: begin"

USER_NAME=mishra_sanjeev_gmail_com

# Wait up to 60s for network reachability — boot-time DNS / route
# setup can take a few seconds after the kernel is up.
for i in $(seq 1 30); do
  if curl -sS -m 5 https://www.google.com > /dev/null 2>&1; then
    echo "startup-script: network up after ${i}x2s"
    break
  fi
  sleep 2
done

# Run the screen launches as the developer user (their home holds the
# scripts + cloud-sql-proxy already authenticated under their gcloud
# config). Quoted heredoc so $vars don't expand on the root side.
su - "$USER_NAME" <<'EOF'
set -uo pipefail

# Quietly skip if a screen of that name is already alive (handles the
# rare case where the script gets re-invoked manually).
ensure_screen() {
  local name="$1"; shift
  local cmd="$*"
  if screen -ls 2>/dev/null | grep -q "\.${name}\b"; then
    echo "ensure_screen: ${name} already running"
    return 0
  fi
  screen -dmS "$name" bash -c "$cmd; exec bash"
  echo "ensure_screen: ${name} launched"
}

# 1) cloud-sql-proxy (must come first; sweeps depend on :5432).
ensure_screen sql_proxy 'cloud-sql-proxy --port 5432 perfect-period-305406:asia-south1:caseops-db'

# Wait up to 30s for proxy to be listening before kicking sweeps.
for i in $(seq 1 15); do
  if ss -lnt | grep -q ':5432'; then
    echo "sql_proxy: listening after ${i}x2s"
    break
  fi
  sleep 2
done
if ! ss -lnt | grep -q ':5432'; then
  echo "ERROR sql_proxy not listening after 30s — sweeps will fail; not launching"
  exit 1
fi

# 2) EN sweep + HC-all sweep.
ensure_screen en_sweep 'cd ~ && ~/run_sweep_en.sh'
ensure_screen hc_sweep_all 'cd ~ && ~/run_sweep_hc_all.sh'

screen -ls
EOF

echo "startup-script: end"
