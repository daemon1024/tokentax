#!/bin/bash
# Record a list of rca-lab captures, one at a time, into the dataset. One line per capture in the plan:
#     <name> <scenario|healthy> <baseline_s> <fault_s> <recovery_s>
#
#   infra/rcalab_campaign.sh infra/rcalab_campaign_plan.txt
#
# Between captures: waits while data/rcalab/.campaign_pause exists (so host-heavy work, e.g. a local
# model, never overlaps a recording window); stops cleanly if data/rcalab/.campaign_stop exists.
# Each capture is finished by scripts/rcalab_dataset_meta.py (meta, SHA256SUMS, backup, manifest) and
# gated by scripts/rcalab_gate.py. Names already in the manifest with status ok are not re-recorded.
set -uo pipefail
PLAN=$1
REPO=$(cd "$(dirname "$0")/.." && pwd)
PY=$REPO/.venv/bin/python
CTL=$REPO/data/rcalab
log() { echo "[$(date -u +%FT%TZ)] $*"; }
done_ok() { $PY -c 'import json,sys; m=json.load(open(sys.argv[1])); print(any(e["name"]==sys.argv[2] and e.get("status")=="ok" for e in m["captures"]))' \
              "$REPO/results/datasets/rcalab_manifest.json" "$1" 2>/dev/null; }

grep -v '^\s*#' "$PLAN" | grep -v '^\s*$' | while read -r NAME SC B F R; do
  [ -e "$CTL/.campaign_stop" ] && { log "stop file present; ending campaign before $NAME"; break; }
  while [ -e "$CTL/.campaign_pause" ]; do sleep 15; done
  [ "$(done_ok "$NAME")" = True ] && { log "$NAME already in manifest; skipping"; continue; }
  log "=== $NAME ($SC) baseline=${B}s fault=${F}s recovery=${R}s"
  "$REPO/infra/rcalab_capture_dataset.sh" "$NAME" "$SC" "$B" "$F" "$R" </dev/null
  rc=$?
  if [ $rc = 0 ] || [ $rc = 3 ]; then
    $PY "$REPO/scripts/rcalab_dataset_meta.py" "data/rcalab/$NAME" </dev/null 2>&1 | tail -2
    if [ $rc = 0 ] && [ "$SC" != healthy ]; then
      $PY "$REPO/scripts/rcalab_gate.py" "data/rcalab/$NAME" --json "results/runs/rcalab_gate/$NAME.json" </dev/null 2>&1 \
        | grep -E "^VERDICT|^   " | head -4
    fi
  else
    log "$NAME: driver exit $rc (preflight abort, nothing recorded); waiting 120s before the next"
    sleep 120
  fi
done
log "campaign finished"
