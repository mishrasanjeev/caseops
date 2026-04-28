# Container for the hourly ingest-VM watchdog.
# Runs as a Cloud Run Job, triggered by Cloud Scheduler.
# See scripts/cron/deploy-watchdog.sh for the GCP-side wiring.

FROM google/cloud-sdk:slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bc curl python3 \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/watchdog
COPY ingest-vm-watchdog.sh /opt/watchdog/ingest-vm-watchdog.sh
COPY entrypoint.sh /opt/watchdog/entrypoint.sh
RUN chmod +x /opt/watchdog/ingest-vm-watchdog.sh /opt/watchdog/entrypoint.sh

ENV QA_COOKIE_FILE=/secrets/qa-storage.json \
    WATCHDOG_LOG=/tmp/watchdog.log \
    INGEST_VM_NAME=caseops-ingest-vm \
    INGEST_VM_ZONE=asia-south1-c \
    INGEST_VM_PROJECT=perfect-period-305406

ENTRYPOINT ["/opt/watchdog/entrypoint.sh"]
