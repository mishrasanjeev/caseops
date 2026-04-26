#!/bin/bash
# All-HC EN-only sweep launcher — 2026-04-26 PM directive from user:
# "For all high courts maps 2025-2010 data, keep vector embedding
#  quality above 4.5+ on the scale of 0 to 5."
#
# Coverage: 24 High Courts × 16 years (2025-2010) = 384 buckets.
# Per-bucket pipeline: ingest → Layer-2 metadata → title-chunk embed
#   → HNSW probe → 0-5 rating (per CLAUDE.md vector-embedding rules).
# Quality enforcement: halt sweep if a bucket rates <4.5/5 — caller
#   must investigate before resuming. Transient INGEST-FAIL (S3
#   connection errors etc.) does NOT halt; we move on to next bucket
#   so a bad day on S3 doesn't block weeks of work.
#
# Sourced helpers (log, parse_probe, run_bucket) come from run_sweep.sh.
set -u

# Reuse env exports + helper function definitions from run_sweep.sh
# (the part before the SC sweep loop "GCE SWEEP START" marker).
END_LINE=$(grep -n "GCE SWEEP START" ~/run_sweep.sh | head -1 | cut -d: -f1)
END_LINE=$((END_LINE - 1))
. <(head -n "$END_LINE" ~/run_sweep.sh)

# Use a dedicated state + ratings log so this sweep doesn't collide
# with the SC en_sweep state.
STATE=~/logs/sweep_state.hc_all.txt
RATINGS=~/logs/ratings.hc_all.log
FLOOR="4.5"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$STATE"; }

export CASEOPS_VOYAGE_DAILY_CAP_USD=20

log "HC-ALL SWEEP START (24 HCs × 2025-2010, EN-only, floor=$FLOOR, voyage_cap=$CASEOPS_VOYAGE_DAILY_CAP_USD)"

# All 24 distinct High Courts in HC_COURT_CATALOG (services/corpus_ingest.py).
# Aliases (mumbai, chennai, bangalore, kolkata, odisha) excluded — they
# map to the same court_code so we'd double-ingest.
#
# Priority order per user 2026-04-26 PM:
#   1. delhi  2. allahabad  3. bombay (Mumbai)  4. calcutta (Kolkata)
#   5. madras  6. karnataka  7. telangana  → then alphabetical for rest.
HC_LIST=(
  delhi allahabad bombay calcutta madras karnataka telangana
  andhra-pradesh chhattisgarh gujarat himachal jammu-kashmir
  jharkhand kerala madhya-pradesh manipur meghalaya orissa
  patna punjab rajasthan sikkim tripura uttarakhand
)

# Year range 2025 down to 2010 per user directive.
YEAR_LIST=(2025 2024 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010)

run_bucket_with_floor_halt() {
  local label="$1"; shift
  run_bucket "$label" "" "$@"
  # Pull the most recent RATING line for this bucket from the master
  # ratings log to enforce the floor. parse_probe inside run_bucket
  # writes one line per bucket to RATINGS via "echo ... >> $RATINGS"
  # (note: that writes to the PARENT scope's $RATINGS — which is now
  # ratings.hc_all.log, not ratings.log). So the latest entry is ours.
  local rating
  rating=$(grep "bucket=$label " "$RATINGS" 2>/dev/null | tail -1 \
           | grep -oE "rating=[0-9.]+" | cut -d= -f2)
  if [[ -z "$rating" ]]; then
    log "FLOOR-CHECK SKIP $label (no rating line — probe likely produced no output)"
    return 0
  fi
  local below
  below=$(awk -v r="$rating" -v f="$FLOOR" "BEGIN{print (r+0 < f+0) ? 1 : 0}")
  if [[ "$below" = "1" ]]; then
    log "FLOOR-HALT $label rating=$rating below=$FLOOR — sweep STOPPED for investigation"
    log "To resume: investigate $HOME/logs/ingest_buckets/$label.{titles,probe}.log, then re-launch this script (it will skip already-rated buckets via INGEST-DUP path)."
    exit 1
  fi
  log "FLOOR-OK $label rating=$rating ≥ $FLOOR"
  return 0
}

for court in "${HC_LIST[@]}"; do
  for year in "${YEAR_LIST[@]}"; do
    label="hc-$court-$year"
    # Skip buckets already rated >=$FLOOR in any prior sweep (state file).
    if grep -qE "bucket=$label.*rating=4\.[5-9]|bucket=$label.*rating=5\." \
       ~/logs/ratings.log ~/logs/ratings.hc.log ~/logs/ratings.hc_all.log 2>/dev/null; then
      log "SKIP $label (already rated >=$FLOOR in prior run)"
      continue
    fi
    # --limit 20000 (vs prior 2000): the prior cap meant we re-listed
    # the SAME first 2000 S3 keys per (court, year) every run. With
    # 9,224 HC docs already in DB across 24 HCs × 16 years, most
    # (court, year) buckets have docs already. The 2000-cap halted
    # growth long before reaching un-ingested docs. 20000 lets the
    # ingester actually walk the full year's listing and discover
    # genuinely new docs.
    run_bucket_with_floor_halt "$label" \
      --from-s3 --court hc --hc-courts "$court" --year "$year" \
      --min-chars 4000 --limit 20000 --language-suffix EN
  done
done

log "HC-ALL SWEEP COMPLETE"
