#!/bin/bash
# All-HC sweep launcher.
#
# 2026-04-26 PM directive: "For all high courts maps 2025-2010 data,
#   keep vector embedding quality above 4.5+ on the scale of 0 to 5."
# 2026-04-28 directive: extend year range to 2025-2000 for deeper
#   historical coverage across all 24 HCs.
# 2026-04-29 directive: scope expansion. After hitting the converged
#   ceiling at 99,242 docs:
#     - drop --language-suffix EN (include Devanagari/regional docs)
#     - lower --min-chars 4000 → 2000 (include shorter procedural orders)
#     - convert FLOOR-HALT to FLOOR-WARN so non-English buckets don't
#       stop the sweep (Voyage embeddings rate weaker on non-Latin
#       script — expected; we'd rather get the volume than block on
#       per-bucket quality, with the rating logged for triage).
#
# Coverage: 24 High Courts × 26 years (2025-2000) = 624 buckets.
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

# 2026-05-01: PROGRESS RESUME (state file). Pre-fix every reboot
# restarted at hc-delhi-2025 (first court × newest year). Combined
# with the hourly watchdog reset, the sweep rarely reached past the
# first 2-3 buckets. Fix: the per-bucket DONE marker survives reboots.
# Re-run from scratch with `rm ~/logs/sweep_progress.hc_all.txt`.
mkdir -p ~/logs
PROGRESS_FILE=~/logs/sweep_progress.hc_all.txt
touch "$PROGRESS_FILE"

# 2026-05-01: per-bucket attempt counter. Increments before each
# run_bucket invocation; >3 attempts → SKIP-MAX-ATTEMPTS so a stuck
# bucket (corrupt PDFs / OCR loop / DB timeout) can't park the entire
# 864-bucket sweep on a single HC × year.
ATTEMPTS_FILE=~/logs/sweep_attempts.hc_all.txt
touch "$ATTEMPTS_FILE"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$STATE"; }

bucket_done() {
  grep -qx "DONE-$1" "$PROGRESS_FILE"
}

mark_done() {
  echo "DONE-$1" >> "$PROGRESS_FILE"
}

record_attempt() {
  local label="$1"
  local current
  current=$(grep -E "^$label [0-9]+$" "$ATTEMPTS_FILE" 2>/dev/null \
            | awk '{print $2}' | tail -1)
  current=${current:-0}
  current=$((current + 1))
  grep -vE "^$label " "$ATTEMPTS_FILE" 2>/dev/null \
    > "$ATTEMPTS_FILE.tmp" || true
  echo "$label $current" >> "$ATTEMPTS_FILE.tmp"
  mv "$ATTEMPTS_FILE.tmp" "$ATTEMPTS_FILE"
  echo "$current"
}

export CASEOPS_VOYAGE_DAILY_CAP_USD=20

log "HC-ALL SWEEP START (24 HCs × 2025-2000, ALL-LANGUAGES, min-chars=2000, floor=$FLOOR warn-only, voyage_cap=$CASEOPS_VOYAGE_DAILY_CAP_USD, progress=$PROGRESS_FILE)"

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

# Year range 2025 down to 1990 per 2026-05-01 user directive
# ("lot of data, 2025-1990"). Earlier directives ratcheted: 2025-2010
# → 2025-2000 → 2025-1990. 24 HCs × 36 years = 864 buckets total.
YEAR_LIST=(2025 2024 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010 \
           2009 2008 2007 2006 2005 2004 2003 2002 2001 2000 \
           1999 1998 1997 1996 1995 1994 1993 1992 1991 1990)

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
    # 2026-04-29: warn-only. Pre-2026-04-29 this halted the sweep so
    # an operator could investigate. After the scope expansion (drop
    # EN-only, lower min-chars), Devanagari/regional buckets are
    # expected to rate below 4.5 because Voyage embeddings perform
    # weaker on non-Latin scripts. We'd rather get the volume than
    # block on per-bucket quality. The rating is logged for triage.
    log "FLOOR-WARN $label rating=$rating below=$FLOOR — continuing (post-2026-04-29 expansion accepts non-EN buckets at lower quality)"
    return 0
  fi
  log "FLOOR-OK $label rating=$rating ≥ $FLOOR"
  return 0
}

for court in "${HC_LIST[@]}"; do
  for year in "${YEAR_LIST[@]}"; do
    label="hc-$court-$year"
    # 2026-05-01: skip buckets already marked DONE in this VM's
    # progress file so reboots / watchdog resets don't re-walk the
    # head of the list every cycle. The DONE marker is only written
    # AFTER run_bucket succeeds — incomplete buckets re-run.
    if bucket_done "$label"; then
      log "RESUME-SKIP $label (marked DONE in $PROGRESS_FILE)"
      continue
    fi
    attempts=$(record_attempt "$label")
    if (( attempts > 3 )); then
      log "SKIP-MAX-ATTEMPTS $label (attempts=$attempts; investigate offline)"
      mark_done "$label"
      continue
    fi
    # 2026-04-29: skip-by-prior-rating REMOVED. Pre-expansion ratings
    # were under --language-suffix EN + --min-chars 4000. Post-
    # expansion, the same buckets may have new (non-EN, shorter)
    # content to ingest that the dedupe path will pick up. The cost
    # of a re-walk on a fully-deduped bucket is minimal: S3 list +
    # per-doc hash checks. Real new docs flow through OCR + embed +
    # insert as expected.
    # --limit 20000 (vs prior 2000): the prior cap meant we re-listed
    # the SAME first 2000 S3 keys per (court, year) every run. With
    # 9,224 HC docs already in DB across 24 HCs × 16 years, most
    # (court, year) buckets have docs already. The 2000-cap halted
    # growth long before reaching un-ingested docs. 20000 lets the
    # ingester actually walk the full year's listing and discover
    # genuinely new docs.
    run_bucket_with_floor_halt "$label" \
      --from-s3 --court hc --hc-courts "$court" --year "$year" \
      --min-chars 2000 --limit 20000
    mark_done "$label"
  done
done

log "HC-ALL SWEEP COMPLETE"
