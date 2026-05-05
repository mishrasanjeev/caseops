#!/bin/bash
# SC + HC sweep launcher for the ingest VM.
#
# 2026-04-26 PM: shipped as "EN-only" with --language-suffix EN +
#   --min-chars 4000. Original scope: SC 2025-1990 + HC 2025-2000
#   for the 7 priority HCs (delhi/allahabad/bombay/calcutta/madras/
#   karnataka/telangana). Tracked in feedback_corpus_spend_audit
#   memory: $20/day Voyage cap.
#
# 2026-04-29: scope expansion (corpus converged at 99,242 docs under
#   prior scope; need MORE volume). HC stayed all-language, but SC is
#   back to --language-suffix EN after the 2026-05-05 stuck-ingest
#   incident: old SC tarballs contain thousands of regional/corrupt PDFs
#   that repeatedly fall through pdfminer + OCR and starve English
#   progress. Regional SC needs a separate language-tagged pipeline.
#   The other expansion knobs remain:
#     - lower --min-chars 4000 → 2000 (procedural orders included)
#     - --limit 2000 → 20000 (mirrors run_sweep_hc_all.sh — original
#       2000-cap silently halted at S3-list head and missed real new
#       docs further into the listing)
#   Filename suffix "_en" preserved for compatibility with the VM's
#   startup-script (scripts/vm/startup-script.sh) and prior tooling
#   that grep for the screen name.
#
# 2026-05-01: PROGRESS RESUME (state file). Pre-fix, every reboot
#   restarted the launcher at sc-2024 (newest year). With the hourly
#   watchdog reset + occasional VM reboots, the sweep burned 15-20
#   min per cycle on sc-2024's already-ingested dups and rarely
#   reached deeper buckets. Fix: ~/logs/sweep_progress.en.txt records
#   each bucket on successful run_bucket; on startup we skip buckets
#   marked DONE so progress survives reboots. Re-run from scratch
#   with `rm ~/logs/sweep_progress.en.txt`.
#
# Lives at ~/run_sweep_en.sh on caseops-ingest-vm. Canonical copy
# in this repo so future scope edits flow through git instead of
# living only on the VM.
set -u

# Reuse env exports + helper function definitions from run_sweep.sh
# (the part before the SC sweep loop "GCE SWEEP START" marker).
END_LINE=$(grep -n "GCE SWEEP START" ~/run_sweep.sh | head -1 | cut -d: -f1)
END_LINE=$((END_LINE - 1))
. <(head -n "$END_LINE" ~/run_sweep.sh)

export CASEOPS_VOYAGE_DAILY_CAP_USD=20

# Dedicated master log + progress state — keeps en_sweep cycles from
# stomping over each other and gives a single source of truth for
# "what has actually completed".
mkdir -p ~/logs
EN_MASTER_LOG=~/logs/en_sweep_master.log
PROGRESS_FILE=~/logs/sweep_progress.en.txt
touch "$PROGRESS_FILE"

# Override the sourced `log` so every line is also appended to the
# launcher's own master log + progress file. Both files are created
# with append semantics so reboots stack new lines on top of history
# (pre-fix the new launcher truncated en_sweep_master.log on every
# restart, leaving 0% visibility into what had happened).
log() {
  echo "[$(date -Iseconds)] $*" | tee -a "$EN_MASTER_LOG"
}

bucket_done() {
  grep -qx "DONE-$1" "$PROGRESS_FILE"
}

mark_done() {
  echo "DONE-$1" >> "$PROGRESS_FILE"
}

# 2026-05-01: per-bucket attempt counter. Used to skip a bucket after
# 3 failed attempts so a stuck S3-list / OCR loop / DB-timeout doesn't
# block the rest of the sweep. State lives in a sibling file so the
# DONE-marker file stays a clean source of "what's complete".
ATTEMPTS_FILE=~/logs/sweep_attempts.en.txt
touch "$ATTEMPTS_FILE"

record_attempt() {
  # Increment the attempt count for $1 and echo the new count.
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

log "EN-SWEEP START (SC 2024-1990 EN-only + HC 2025-2000 all-languages, min-chars=2000, voyage_cap=$CASEOPS_VOYAGE_DAILY_CAP_USD, progress=$PROGRESS_FILE)"

# SC: skip years already rated >=4.5 in prior runs (per ratings.log).
# Skipped: 2024 (script-flagged), 2023 (sweep-state SKIP), 2021/2020/
# 2019/2018/2017/2016/2015 (>=4.5 rated under EN-only; we still want
# those years re-walked under expanded scope so the skip is dropped
# 2026-04-29 along with the EN filter).
for year in 2024 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010 \
           2009 2008 2007 2006 2005 2004 2003 2002 2001 2000 \
           1999 1998 1997 1996 1995 1994 1993 1992 1991 1990; do
  label="sc-$year"
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
  # 2026-05-01: SC failures used to halt the sweep with `exit $rc`.
  # Replaced with skip-after-3-attempts to keep the loop moving when
  # a single bucket is stuck. The attempt counter is persistent so a
  # subsequent restart picks up where we left off.
  run_bucket "$label" "$year-$year" \
    --from-s3 --court sc --year "$year" --min-chars 2000 --limit 20000 --language-suffix EN
  rc=$?
  if [[ $rc -ne 0 ]]; then
    log "BUCKET-FAIL $label (rc=$rc, attempt=$attempts) — continuing"
    continue
  fi
  mark_done "$label"
done

log "SC DONE - starting HC priority-7 (run_sweep_hc_all.sh covers full 24-HC sweep)"

# 2026-05-01: HC year range extended 2025-2000 → 2025-1990 to mirror
# the SC sweep's depth. User directive: "lot of data to work on,
# 2025-1990".
for court in delhi allahabad calcutta telangana madras karnataka bombay; do
  for year in 2025 2024 2023 2022 2021 2020 2019 2018 2017 2016 2015 2014 2013 2012 2011 2010 \
             2009 2008 2007 2006 2005 2004 2003 2002 2001 2000 \
             1999 1998 1997 1996 1995 1994 1993 1992 1991 1990; do
    label="hc-$court-$year"
    if bucket_done "$label"; then
      log "RESUME-SKIP $label (marked DONE in $PROGRESS_FILE)"
      continue
    fi
    # 2026-05-01: skip-after-N-attempts. Each invocation of this loop
    # records an ATTEMPT entry for the bucket. If a bucket has been
    # attempted >=3 times without ever marking DONE (probably stuck on
    # a corrupt PDF / never-ending OCR loop), we mark it DONE anyway
    # and move on — staying parked on one HC × year would block the
    # other 800+ buckets.
    attempts=$(record_attempt "$label")
    if (( attempts > 3 )); then
      log "SKIP-MAX-ATTEMPTS $label (attempts=$attempts; investigate offline)"
      mark_done "$label"
      continue
    fi
    run_bucket "$label" "" \
      --from-s3 --court hc --hc-courts "$court" --year "$year" --min-chars 2000 --limit 20000
    rc=$?
    if [[ $rc -ne 0 ]]; then
      log "BUCKET-FAIL $label (rc=$rc, attempt=$attempts) — continuing"
      continue
    fi
    mark_done "$label"
  done
done

log "EN-SWEEP DONE"
