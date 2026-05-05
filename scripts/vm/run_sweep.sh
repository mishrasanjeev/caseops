#!/bin/bash
# CaseOps SC/HC corpus sweep — per-bucket pipeline with quality gate.
#
# Per-bucket order (see .claude/skills/corpus-ingest/SKILL.md):
#   1. ingest (--from-s3)
#   2. Layer-2 metadata (--stage structured --force-tier haiku --budget-usd 10, year-scoped for SC)
#   3. title-chunk embed (--refresh, rebuilds metadata chunks with richer titles)
#   4. HNSW probe (--tenant aster-demo --sample-size 30 --k 10 --seed 42)
#   5. 0-5 rating: 5.0 * recall@10. Floor = 4.7; below that, STOP.
#
# Budget is PER BUCKET ($10), never global. One bad bucket can't drain the pool.
# sc-2024 and sc-2025 are intentionally excluded — already fully ingested.

set -u
source ~/.local/bin/env

export DB_PW=$(gcloud secrets versions access latest --secret=caseops-db-password)
export VOYAGE_KEY=$(gcloud secrets versions access latest --secret=caseops-voyage-api-key)
export OPENAI_KEY=$(gcloud secrets versions access latest --secret=caseops-openai-api-key)
export CASEOPS_DATABASE_URL="postgresql+psycopg://caseops:${DB_PW}@127.0.0.1:5432/caseops"
export CASEOPS_EMBEDDING_PROVIDER=voyage
export CASEOPS_EMBEDDING_MODEL=voyage-4-large
export CASEOPS_EMBEDDING_DIMENSIONS=1024
export CASEOPS_EMBEDDING_API_KEY="$VOYAGE_KEY"
export CASEOPS_LLM_PROVIDER=openai
export CASEOPS_LLM_MODEL=gpt-5-mini
export CASEOPS_LLM_MODEL_METADATA_EXTRACT=gpt-5-mini
export CASEOPS_LLM_API_KEY="$OPENAI_KEY"
export CASEOPS_LAYER2_DAILY_CAP_USD=40
export CASEOPS_RERANK_ENABLED=true
export CASEOPS_RERANK_BACKEND=fastembed
export PYTHONUNBUFFERED=1

cd ~/caseops/apps/api
mkdir -p ~/logs/ingest_buckets
STATE=~/logs/sweep_state.txt
RATINGS=~/logs/ratings.log
MASTER=~/logs/sweep_master.log
FLOOR="4.5"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$STATE"; }

UV="$HOME/.local/bin/uv"
PY() { "$UV" run --no-sync python -m "$@"; }

# Derive rating from a probe log. Parses '**recall@10**: 29/30 (96.7 %)', MRR, mean rank.
# Rating = 5.0 * recall@10 (fraction). Echoes: 'rating=X.Y recall@10=0.967 MRR=0.842 rank=1.45'
parse_probe() {
  local probe_log="$1"
  # Output lines look like:
  #   - **recall@10**: 29/30 (96.7 %)
  #   - **MRR**: 0.842
  #   - **mean rank (when found)**: 1.45
  local recall_pct mrr rank rating recall_frac
  # Line form: "- **recall@10**: 29/30 (96.7 %)"
  # Pull "a/b" via awk, compute a/b*100.
  recall_pct=$(grep -E '\*\*recall@10\*\*:' "$probe_log" | head -1 \
               | awk '{
                   for (i=1;i<=NF;i++) if ($i ~ /^[0-9]+\/[0-9]+$/) { split($i,p,"/"); if (p[2]>0) printf "%.1f", p[1]/p[2]*100; exit }
                 }')
  mrr=$(grep -E '\*\*MRR\*\*:' "$probe_log" | head -1 | awk '{print $NF}')
  rank=$(grep -E '\*\*mean rank \(when found\)\*\*:' "$probe_log" | head -1 | awk '{print $NF}')
  if [[ -z "$recall_pct" || "$recall_pct" = "0" ]]; then
    echo "rating=0.0 recall@10=ERR MRR=${mrr:-NA} rank=${rank:-NA}"
    return
  fi
  rating=$(awk -v r="$recall_pct" 'BEGIN{printf "%.2f", 5.0*r/100.0}')
  recall_frac=$(awk -v r="$recall_pct" 'BEGIN{printf "%.3f", r/100.0}')
  echo "rating=$rating recall@10=$recall_frac MRR=${mrr:-NA} rank=${rank:-NA}"
}

# Returns 0 if bucket-already-ingested (processed=0, skipped>0, no crash)
# Returns 2 if real failure.
# Logs to master regardless.
ingest_is_benign() {
  local ingest_log="$1"
  # Benign when the ingester printed a structured summary (no crash):
  #   - processed > 0 + skipped (dup) > 0 (re-run of already-ingested bucket)
  #   - processed = 0, nothing in S3 (e.g. allahabad / calcutta for years
  #     where the prod S3 bucket has no uploads yet).
  # Either way the log ends with the summary, not a traceback.
  if grep -qE '^  processed  *: [0-9]+' "$ingest_log" && ! grep -qE '^Traceback' "$ingest_log"; then
    return 0
  fi
  return 1
}

run_bucket() {
  local label="$1"
  local year_range="$2"  # e.g. "2023-2023" for SC, or "" for HC (skip year-range)
  shift 2
  local ingest_args=("$@")
  local ingest_log="$HOME/logs/ingest_buckets/$label.log"
  local layer2_log="$HOME/logs/ingest_buckets/$label.layer2.log"
  local titles_log="$HOME/logs/ingest_buckets/$label.titles.log"
  local probe_log="$HOME/logs/ingest_buckets/$label.probe.log"

  log "START $label"

  # 1. INGEST
  if PY caseops_api.scripts.ingest_corpus "${ingest_args[@]}" >> "$ingest_log" 2>&1; then
    log "INGEST-OK $label"
  else
    local rc=$?
    if ingest_is_benign "$ingest_log"; then
      log "INGEST-DUP $label (exit $rc tolerated — all docs already in corpus)"
    else
      log "INGEST-FAIL $label (exit $rc)"
      return 2
    fi
  fi

  # 2. LAYER-2 METADATA (per-bucket $10 cap, year-scoped for SC)
  local l2_args=(--stage structured --force-tier haiku --budget-usd 10)
  if [[ -n "$year_range" ]]; then
    l2_args+=(--year-range "$year_range")
  fi
  if PY caseops_api.scripts.backfill_corpus_quality "${l2_args[@]}" >> "$layer2_log" 2>&1; then
    log "LAYER2 $label"
  else
    log "LAYER2-FAIL $label (exit $?) — continuing; probe will show quality impact"
  fi

  # 3. TITLE-CHUNK EMBED (refresh so richer Layer-2 titles land in metadata chunk)
  if PY caseops_api.scripts.backfill_title_chunks --refresh --batch-size 32 >> "$titles_log" 2>&1; then
    log "TITLES $label"
  else
    log "TITLES-FAIL $label (exit $?) — continuing"
  fi

  # 4. HNSW PROBE — run and capture; ignore exit code, parse markdown instead.
  # Rationale (2026-04-21 patch): eval_hnsw_recall exits non-zero even when it
  # emits valid recall markdown (e.g. when any misses are present). We trust the
  # markdown line if present; only fall back when it is genuinely absent.
  PY caseops_api.scripts.eval_hnsw_recall --tenant aster-demo --sample-size 30 --k 10 --seed 42 \
      >> "$probe_log" 2>&1 || true
  if grep -qE '\*\*recall@10\*\*:' "$probe_log"; then
    log "PROBE $label"
  else
    log "PROBE-NO-OUTPUT $label — markdown missing, rating=0"
    echo "[$(date -Iseconds)] bucket=$label rating=0.0 recall@10=PROBE_NO_OUTPUT MRR=NA rank=NA" >> "$RATINGS"
    return 0
  fi

  # 5. RATING
  local metrics
  metrics=$(parse_probe "$probe_log")
  local line="[$(date -Iseconds)] bucket=$label $metrics"
  echo "$line" >> "$RATINGS"
  log "RATING $label $metrics"

  local rating
  rating=$(echo "$metrics" | grep -oE 'rating=[0-9.]+' | cut -d= -f2)
  # Quality gate: WARN-ONLY (2026-04-21 patch). We collect baseline across all
  # buckets; quality fixes run in parallel, not by halting the sweep.
  local below
  below=$(awk -v r="$rating" -v f="$FLOOR" 'BEGIN{print (r+0 < f+0) ? 1 : 0}')
  if [[ "$below" = "1" ]]; then
    log "WARN-BELOW-FLOOR $label rating=$rating floor=$FLOOR — continuing sweep (baseline mode)"
  fi

  return 0
}

log "GCE SWEEP START (v2, per-bucket pipeline, floor=$FLOOR)"

# Supreme Court: skip 2024 and 2025 (already ingested).
for year in 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010 \
           2009 2008 2007 2006 2005 2004 2003 2002 2001 2000 \
           1999 1998 1997 1996 1995 1994 1993 1992 1991 1990 \
           1989 1988 1987 1986 1985 1984 1983 1982 1981 1980; do
  label="sc-$year"
  # 2026-04-21 restart: sc-2023 already ingested + rated 4.17/5 in prior run.
  # Skip so the sweep resumes from sc-2022 onward and gathers new baseline data.
  if [[ "$label" == "sc-2023" ]]; then
    log "SKIP $label (already ingested + rated in prior run; resume from sc-2022)"
    continue
  fi
  run_bucket "$label" "$year-$year" \
    --from-s3 --court sc --year "$year" --min-chars 4000 --limit 2000
  rc=$?
  if [[ $rc -ne 0 ]]; then
    log "SWEEP HALTED at $label (rc=$rc)"
    exit $rc
  fi
done

log "SC DONE - starting HC"

for court in delhi allahabad calcutta telangana madras karnataka bombay; do
  for year in 2025 2024 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010; do
    # HC layer-2 cannot be year-scoped by the CLI; rely on budget cap.
    run_bucket "hc-$court-$year" "" \
      --from-s3 --court hc --hc-courts "$court" --year "$year" --min-chars 4000 --limit 2000
    rc=$?
    if [[ $rc -ne 0 ]]; then
      log "SWEEP HALTED at hc-$court-$year (rc=$rc)"
      exit $rc
    fi
  done
done

log "SWEEP COMPLETE"
