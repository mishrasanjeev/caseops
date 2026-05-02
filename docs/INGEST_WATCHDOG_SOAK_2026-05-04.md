# Ingest Watchdog 48h Soak Verification — fire 2026-05-04 ~07:30 IST

**Purpose.** Verify the durable ingest watchdog deployed in commit `8501343`
(2026-05-02) ran cleanly for 48h, then retire the obsolete predecessor at
`scripts/cron/`.

**Why this is a manual checklist, not an agent.** The verification needs
authenticated access to GCP (`gcloud`, Cloud SQL, Cloud Scheduler, IAM) plus
`gh` for the PR. A remote Claude agent in Anthropic's cloud has none of those
credentials. Workstation gcloud + psql is the right tool.

Background: `~/.claude/projects/C--Users-mishr-caseops/memory/feedback_ingestor_vm_hourly_watchdog.md`

---

## Step 1 — Watchdog ran cleanly (no reset-loops, no exceptions)

```bash
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=caseops-ingest-watchdog' \
  --limit=300 --freshness=48h \
  --format='value(timestamp,textPayload)'
```

**Pass criteria:**

- One log group every 15 minutes (`*/15`), no gaps > 30 min.
- Most lines are `stale_sec=<small> threshold=7200` followed by `ok`.
- Any `STUCK — resetting` line is followed within 30 min of cooldown by
  `stale_sec=<small>` and `ok` — not by another `STUCK` (that would mean the
  reset didn't fix things and we have a deeper problem).
- No Python tracebacks, no `compute_v1` errors, no DB connection failures.

**If pass → continue. If fail → STOP, jump to Step 5.**

## Step 2 — Ingest stayed flowing

Run the same cloud-sql-proxy + psql recipe used on 2026-05-02:

```bash
cloud-sql-proxy --port 15433 perfect-period-305406:asia-south1:caseops-db &
PGPASSWORD="$(gcloud secrets versions access latest --secret=caseops-db-password)" \
  "/c/Program Files/PostgreSQL/17/bin/psql.exe" \
  -h 127.0.0.1 -p 15433 -U caseops -d caseops -At -F '|' -c "
SELECT date_trunc('day', ingested_at AT TIME ZONE 'UTC')::date AS d,
       COUNT(*) AS docs
FROM authority_documents
WHERE ingested_at > now() - interval '4 days'
GROUP BY 1 ORDER BY 1 DESC;
SELECT MAX(ingested_at)::text FROM authority_documents;
"
taskkill //F //IM cloud-sql-proxy.exe
```

**Pass criteria:**

- Every day in the last 3 has > 0 docs (no zero-day stalls like 2026-04-30).
- `MAX(ingested_at)` is within the last 2h of the time you run this.

**If pass → continue. If fail → STOP, jump to Step 5.**

## Step 3 — Scheduler still ENABLED

```bash
gcloud scheduler jobs describe caseops-ingest-watchdog-15m \
  --location=asia-south1 \
  --format='value(state,schedule,httpTarget.uri)'
```

**Pass criteria:** `ENABLED  */15 * * * *  https://asia-south1-run.googleapis.com/.../caseops-ingest-watchdog:run`

## Step 4 — Cleanup (only if Steps 1–3 all green)

### 4a. Repo deletion + PR

```bash
git checkout -b chore/retire-old-watchdog
git rm -r scripts/cron/
git commit -m "$(cat <<'EOF'
Retire scripts/cron/ ingest watchdog (superseded by scripts/ingest-watchdog/)

The 2026-04-28 watchdog under scripts/cron/ was found PAUSED in prod Cloud
Scheduler on 2026-05-02 (had been silent for days). Replaced in commit 8501343
with scripts/ingest-watchdog/ — a simpler DB-backed probe that does not depend
on a QA cookie that can silently expire. After 48h of clean soak, retiring the
old code, scheduler, and SA.
EOF
)"
gh pr create --title "Retire obsolete scripts/cron/ ingest watchdog" \
  --body "Cleanup after 48h soak of the durable replacement deployed in 8501343. See docs/INGEST_WATCHDOG_SOAK_2026-05-04.md for the verification log."
```

### 4b. Delete the paused Cloud Scheduler

```bash
gcloud scheduler jobs delete caseops-ingest-watchdog-trigger \
  --location=asia-south1 --quiet
```

### 4c. Delete the unused service account

First confirm nothing else uses it:

```bash
gcloud projects get-iam-policy perfect-period-305406 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:caseops-watchdog-runtime@perfect-period-305406.iam.gserviceaccount.com" \
  --format='value(bindings.role)'
```

Expected output: only roles related to the watchdog VM/secret. If any other
binding shows up (Cloud Run, BigQuery, etc.), STOP and investigate before
deleting.

```bash
gcloud iam service-accounts delete \
  caseops-watchdog-runtime@perfect-period-305406.iam.gserviceaccount.com --quiet
```

### 4d. Remove the secret if it's only used by the old watchdog

The old code referenced `caseops-qa-storage-state`. Verify no live workload
still pulls it:

```bash
gcloud secrets describe caseops-qa-storage-state --format='value(name)'
gcloud run services list --region=asia-south1 \
  --format='value(spec.template.spec.containers[].env[].valueFrom.secretKeyRef.name)' \
  | grep -i qa-storage || echo "no consumers"
gcloud run jobs list --region=asia-south1 \
  --format='value(spec.template.spec.containers[].env[].valueFrom.secretKeyRef.name)' \
  | grep -i qa-storage || echo "no consumers"
```

If both report `no consumers`, also delete the secret. Otherwise leave it —
it's still feeding something.

### 4e. Update memory + session log

Edit `~/.claude/projects/C--Users-mishr-caseops/memory/feedback_ingestor_vm_hourly_watchdog.md`:

- Remove the entire "Superseded — do NOT use" section (the obsolete code is now gone).
- Append a one-liner under Anchor incident: "Cleanup landed YYYY-MM-DD via PR #N."

Edit `session_log.md` to close the 2026-05-02 thread.

### 4f. Delete this checklist

```bash
git rm docs/INGEST_WATCHDOG_SOAK_2026-05-04.md
git commit -m "Soak verified, checklist retired"
```

## Step 5 — Failure path

If any pass criteria fails:

1. **Do NOT clean up.** The old code stays as a fallback.
2. Capture the failure: copy the relevant log lines + the failing query output
   into `docs/INGEST_WATCHDOG_SOAK_2026-05-04_FAILURE.md`.
3. Triage. Common modes worth checking:
   - Reset-loop → cooldown sentinel label not being read/written correctly,
     check `gcloud compute instances describe caseops-ingest-vm --format='value(labels)'`.
   - Watchdog exceptions → look at the Cloud Run Job revision and rebuild from
     a fixed `scripts/ingest-watchdog/watchdog.py`.
   - Ingest stalled despite watchdog firing → reboot didn't help, suggests a
     non-network failure (Voyage budget cap, Cloud SQL proxy bug, sweep launcher
     wedged). SSH in and inspect screens directly.
4. Postpone cleanup by 48h, re-fire this checklist.
