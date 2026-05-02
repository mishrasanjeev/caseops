# gpt-5-mini Layer-2 Backlog-Drain Verification — fire 2026-05-04

**Purpose.** 48 hours after the Layer-2 model cutover from gpt-5.1 →
gpt-5-mini (commit `2812ec7`, 2026-05-02), verify two things:

1. The 95K-doc backlog actually drained at the predicted rate (~$40/day at
   $0.0009/doc = ~44K docs/day capacity, so ≤2 days to clear).
2. The 4.5+/5 retrieval rubric **holds on the harder, just-Layer-2'd
   backlog cohort** — not just on the small 31-doc pilot from 2026-05-02.
   The pilot rubric had effective n=1 due to a ≤19-probe cohort; this
   verification gets a much bigger sample and re-scores it.

**Why a workstation checklist, not a remote agent.** The verification needs
authenticated `gcloud` + `psql` against `perfect-period-305406` plus voyage
embedding spend. Anthropic-cloud agents have neither.

**Spend authorization (user 2026-05-02): up to $10** for new extraction +
re-embed + rubric runs.

Anchor commits:
- `2812ec7` — gpt-5-mini cutover (CASEOPS_LLM_MODEL_METADATA_EXTRACT)
- `8b3f58e` — A/B plumbing (env override + cohort-window rubric filter)
- `732e037` — per-bucket Layer-2 fix (haiku bucket no longer wiped)
- `c3737e7` — Layer-2 backfill Cloud Run Job + daily scheduler

Memory anchor: `feedback_vector_embedding_pipeline.md` + the A/B summary in
`session_log.md` (2026-05-02 thread).

---

## Step 1 — Did the backlog actually drain?

```bash
cloud-sql-proxy --port 15433 perfect-period-305406:asia-south1:caseops-db &
sleep 4
PGPASSWORD="$(gcloud secrets versions access latest --secret=caseops-db-password)" \
  "/c/Program Files/PostgreSQL/17/bin/psql.exe" \
  -h 127.0.0.1 -p 15433 -U caseops -d caseops -At -F '|' -c "
SELECT
  COUNT(*)                                           AS total,
  COUNT(*) FILTER (WHERE structured_version IS NOT NULL) AS layer2_done,
  COUNT(*) FILTER (WHERE structured_version IS NULL)     AS layer2_pending,
  ROUND(100.0 * COUNT(*) FILTER (WHERE structured_version IS NOT NULL) / COUNT(*), 1) AS pct
FROM authority_documents;
"
taskkill //F //IM cloud-sql-proxy.exe
```

Baseline at 2026-05-02 ~13:30 IST: total=116,937, layer2_done=21,877 (18.7%),
layer2_pending=95,060.

**Pass criteria:** layer2_pending should be **near zero** (within a few
hundred), and layer2_done should be near total. The actual number is fine if
it's >100K; the predicted rate may be over-optimistic.

**If pass → Step 2. If fail → STOP, jump to Step 5.**

## Step 2 — Per-day spend confirms gpt-5-mini was actually used

```bash
PGPASSWORD="$DB_PW" psql ... -c "
SELECT date_trunc('day', created_at AT TIME ZONE 'UTC')::date AS d,
       model, COUNT(*) AS calls,
       SUM(prompt_tokens) AS in_tok,
       SUM(completion_tokens) AS out_tok
FROM model_runs
WHERE purpose = 'metadata_extract' AND created_at > now() - interval '4 days'
GROUP BY 1, 2 ORDER BY 1 DESC, 4 DESC;
"
```

**Pass criteria:** the rows for 2026-05-03 and 2026-05-04 should show `model
= gpt-5-mini` (not gpt-5.1). Per-day input + output tokens × $0.25/$2.00 per
M should sum to within $40/day.

If gpt-5.1 is still showing up after 2026-05-03 — the VM screens didn't
inherit the new env after the 2026-05-02 reboot, OR a screen restart didn't
happen. Check `~/run_sweep.sh` on the VM has `CASEOPS_LLM_MODEL=gpt-5-mini`
and reboot the VM.

## Step 3 — Run the rubric on a much bigger Layer-2'd cohort

The pilot rubric on 2026-05-02 only had 19-20 probes per cohort because the
cohort itself was 22-87 docs. Now the cohort is ≥100K. Sample 100 docs and
run 5 seeds for a robust mean.

```bash
gcloud run jobs update caseops-eval-hnsw-recall \
  --region=asia-south1 \
  --update-env-vars="..." \
  --command=python \
  --args="^|^-m|caseops_api.scripts.eval_hnsw_recall|--tenant|caseops-qa|--sample-size|100|--k|10|--seed|7"

# Then fire 5 seeds in parallel
for SEED in 7 13 42 99 137; do
  gcloud run jobs execute caseops-eval-hnsw-recall \
    --region=asia-south1 \
    --args="^|^-m|caseops_api.scripts.eval_hnsw_recall|--tenant|caseops-qa|--sample-size|100|--k|10|--seed|${SEED}" \
    --async --quiet
done
```

(If all 5 seeds OOM at 8Gi / sample-size=100, drop to sample-size=50 — the
known eval-script tokenizer-cache bug grows memory per probe.)

Aggregate the 5 seeds via the `evaluation_runs` + `evaluation_cases` tables:

```sql
WITH cohort AS (
  SELECT id FROM evaluation_runs
  WHERE suite_name = 'hnsw-recall'
    AND started_at > '2026-05-04 00:00'
)
SELECT
  c.run_id, COUNT(*) AS n,
  (100.0 * COUNT(*) FILTER (WHERE c.status = 'pass') / COUNT(*))::numeric(5,1) AS recall_at_10_pct,
  (SUM(CASE WHEN c.status = 'pass'
            THEN 1.0 / ((c.findings_json::jsonb)->'extra'->>'rank')::numeric ELSE 0 END)
   / COUNT(*))::numeric(5,3) AS mrr,
  AVG(CASE WHEN c.status = 'pass'
           THEN ((c.findings_json::jsonb)->'extra'->>'rank')::numeric END)::numeric(5,2) AS mean_rank
FROM evaluation_cases c JOIN cohort ON c.run_id = cohort.id
GROUP BY c.run_id ORDER BY c.run_id;
```

**Pass criteria:** mean recall@10 ≥ 85%, MRR ≥ 0.70, mean_rank ≤ 3.0 (the
4.5/5 floor). Worst-seed (min) recall@10 ≥ 80% so we know the weak side
hasn't collapsed.

## Step 4 — Cleanup if pass

If Steps 1+2+3 all pass:

- **Delete this checklist.** `git rm docs/GPT5_MINI_BACKLOG_VERIFY_2026-05-04.md`
- **Update memory** `feedback_vector_embedding_pipeline.md` with the new
  ratings (worst seed + mean) so future sessions trust gpt-5-mini.
- **Bump the daily cap down to $10** (or whatever covers the daily forward
  trickle of ~600 docs/day × $0.0009 = ~$0.54). The cap was $40 to drain a
  big backlog; once drained, $10 is plenty headroom.

  ```bash
  gcloud run jobs update caseops-extract-authority-metadata \
    --region=asia-south1 \
    --update-env-vars="CASEOPS_LAYER2_DAILY_USD_CAP=10,CASEOPS_LAYER2_DAILY_CAP_USD=10" \
    --quiet
  # On VM:
  gcloud compute ssh caseops-ingest-vm --zone=asia-south1-c \
    --command="sed -i 's/CASEOPS_LAYER2_DAILY_CAP_USD=40/CASEOPS_LAYER2_DAILY_CAP_USD=10/' /home/mishra_sanjeev_gmail_com/run_sweep.sh && grep CASEOPS_LAYER2_DAILY_CAP_USD /home/mishra_sanjeev_gmail_com/run_sweep.sh"
  ```

## Step 5 — Failure path

If any pass criterion fails:

- Backlog NOT drained (Step 1 fail) → check daily Cloud Run Job logs:
  `gcloud logging read 'resource.labels.job_name=caseops-extract-authority-metadata' --limit=200 --freshness=72h`. Common modes: cap math broken
  (mini calls not writing model_runs?), service account perms, or the daily
  scheduler paused.
- Wrong model (Step 2 fail) → reset VM to pick up new env; redeploy Cloud
  Run Job from `scripts/extract-authority-metadata-job.sh`.
- Rubric drops below 4.5/5 (Step 3 fail) → revisit the model decision. Roll
  back to gpt-5.1 (the safer default) by reverting commit `2812ec7`.
  Capture the failing rubric numbers in `docs/GPT5_MINI_REVISIT_2026-05-04.md`.
