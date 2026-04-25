#!/usr/bin/env bash
# EG-003 (2026-04-25) — wire ClamAV as a Cloud Run sidecar on caseops-api.
#
# Why a script (not a static manifest): the live caseops-api YAML
# carries env vars + secret refs + image tags that change frequently
# (database URL secret, OpenAI key, current image). A static YAML in
# infra/ would drift out of sync. This script:
#
#   1. captures the live YAML via `gcloud run services describe`
#   2. mutates it in Python (add sidecar, add CLAMAV_HOST/PORT env,
#      drop the CLAMAV_REQUIRED=false override, add the
#      container-dependencies annotation so API waits for clamav)
#   3. applies via `gcloud run services replace`
#
# Run it ONCE to wire EG-003. Subsequent `gcloud run deploy --image`
# calls (in scripts/deploy-prod.sh) preserve the multi-container shape
# because gcloud only updates the primary container's image, not the
# sidecar. scripts/deploy-prod.sh verifies the sidecar is still
# present after every deploy.
#
# Usage:
#   scripts/eg003-apply-clamav.sh                       # apply
#   scripts/eg003-apply-clamav.sh --dry-run             # print diff
#
# Cost note (founder-stage, 2026-04-25): minScale stays 0, so idle
# cost stays $0. Per-request handling adds ~$0.00007/sec while clamav
# (1 CPU / 1.5 GiB) shares the request lifecycle. First upload after
# a cold start incurs ~30-60s while clamd loads signatures; if that
# becomes a UX complaint, flip minScale=1 (~$30-50/mo extra).

set -euo pipefail

PROJECT=perfect-period-305406
REGION=asia-south1
SERVICE=caseops-api
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; fi

WORK=$(mktemp -d)
trap "rm -rf '$WORK'" EXIT

echo "=== eg003: capture live YAML ==="
gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT" --format=export \
  > "$WORK/current.yaml"

echo "=== eg003: mutate in Python ==="
# Prefer `python` over `python3` because on Windows `python3` resolves
# to the Microsoft Store launcher which doesn't share site-packages
# with our `python` install (no pyyaml). On Linux/CI both names work.
PY_BIN=python
command -v "$PY_BIN" >/dev/null || PY_BIN=python3
"$PY_BIN" - "$WORK/current.yaml" "$WORK/desired.yaml" <<'PY'
import sys
import yaml

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as fh:
    doc = yaml.safe_load(fh)

template = doc["spec"]["template"]
spec = template["spec"]
containers = spec["containers"]

# Identify the primary (port-bearing) container — that's the API.
api = next(c for c in containers if c.get("ports"))
api["name"] = api.get("name") or "api"

# Drop the explicit CASEOPS_CLAMAV_REQUIRED=false override so the
# env-aware default (True in cloud env) takes over.
api_env = [
    e for e in api.get("env", [])
    if e.get("name") != "CASEOPS_CLAMAV_REQUIRED"
]
# Add CASEOPS_CLAMAV_HOST/PORT so the service can find the sidecar.
existing = {e["name"] for e in api_env}
for name, value in (
    ("CASEOPS_CLAMAV_HOST", "127.0.0.1"),
    ("CASEOPS_CLAMAV_PORT", "3310"),
    ("CASEOPS_CLAMAV_TIMEOUT_S", "60"),
):
    if name not in existing:
        api_env.append({"name": name, "value": value})
api["env"] = api_env

# Wire the sidecar. clamav/clamav:1.4 ships freshclam + clamd; the
# stable-base variant skips freshclam (we want fresh signatures).
sidecar_present = any(c.get("name") == "clamav" for c in containers)
if not sidecar_present:
    containers.append({
        "name": "clamav",
        # Pinned major.minor to avoid surprise upgrades; ClamAV honours
        # stable APIs on patch bumps.
        "image": "clamav/clamav:1.4",
        "resources": {
            "limits": {
                "cpu": "1",
                "memory": "1500Mi",
            },
        },
        "startupProbe": {
            # clamd takes 30-60s to load signatures + freshclam runs
            # on first boot. Give it 4 minutes before Cloud Run treats
            # the container as failed.
            "tcpSocket": {"port": 3310},
            "initialDelaySeconds": 30,
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 24,
        },
    })

# Container-dependencies annotation: API waits for clamav startup
# probe to pass before it starts. Without this, the first few requests
# after a cold start would hit reject_if_infected → 503.
ann = template.setdefault("metadata", {}).setdefault("annotations", {})
ann["run.googleapis.com/container-dependencies"] = '{"api":["clamav"]}'

with open(dst, "w", encoding="utf-8") as fh:
    yaml.safe_dump(doc, fh, sort_keys=False)
print("[ok] desired YAML written")
PY

echo "=== eg003: diff (current → desired) ==="
diff -u "$WORK/current.yaml" "$WORK/desired.yaml" || true

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "=== --dry-run: not applying. Re-run without --dry-run to apply. ==="
  exit 0
fi

echo
echo "=== eg003: apply via 'gcloud run services replace' ==="
gcloud run services replace "$WORK/desired.yaml" \
  --region "$REGION" --project "$PROJECT" --quiet

echo
echo "=== eg003: post-apply revision check ==="
gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --format='value(status.latestReadyRevisionName)'

echo
echo "EG-003 sidecar wired. Next: smoke-test by uploading EICAR through prod."
