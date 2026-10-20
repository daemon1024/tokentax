#!/bin/bash
# Record one rca-lab capture into the replayable dataset (results/datasets/RCALAB_DATASET.md).
#
#   infra/rcalab_capture_dataset.sh <name> <scenario|healthy> <baseline_s> <fault_s> <recovery_s>
#
# Writes data/rcalab/<name>/{logs.jsonl.zst, traces.jsonl.zst, meta_raw.json, cluster/*}; the
# metadata/checksum/backup/manifest step is scripts/rcalab_dataset_meta.py.
#
# Windows (host clock, unix ns):
#   baseline  [B0, B1]  no scenario enabled
#   fault     [F0, F1]  F0 = the controller's "starting run" line was seen; F1 = disable (or the CR's own
#                       duration expiring, whichever is first)
#   recovery  [F1, R1]  scenario disabled, system recovering
# For <scenario> = healthy there is only a baseline window of <baseline_s>.
#
# Safety: never overwrites a capture; refuses to start below MIN_FREE_GB free disk, if the host
# collector is not the lab's export target, if any scenario is active, or if the lab is unhealthy.
# The live collector files are truncated before and after (O_APPEND, so writes restart at offset 0);
# a separate watchdog caps their size.
set -uo pipefail
NAME=$1; SC=$2; BASE_S=$3; FAULT_S=$4; REC_S=$5
CTX=${CTX:-kind-rca-lab}
LIVE=${LIVE:-$HOME/tokentax-capture-v2}
COLL=${COLL:-tokentax-capture2}
RCALAB=${RCALAB:-/Users/daemon1024/play/rca-lab}
MIN_FREE_GB=${MIN_FREE_GB:-8}
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=$REPO/data/rcalab/$NAME
K="kubectl --context $CTX -n default"
CHECK="python3 $REPO/infra/rcalab_effect_check.py --context $CTX"
now_ns() { python3 -c 'import time; print(time.time_ns())'; }
log() { echo "[$(date -u +%H:%M:%S)] $NAME: $*"; }
skip() {   # record WHY nothing was captured, then stop
  mkdir -p "$OUT"
  python3 -c 'import json,sys; json.dump({"name":sys.argv[1],"scenario":sys.argv[2],"status":"skipped",
              "reason":sys.argv[3]}, open(sys.argv[4],"w"), indent=1)' "$NAME" "$SC" "$1" "$OUT/SKIPPED.json"
  log "SKIPPED: $1"; exit 3; }
revert() { [ "$SC" = healthy ] || $K patch maintenancejob "$SC" --type=merge -p '{"spec":{"enabled":false}}' >/dev/null 2>&1 || true; }

# The host collector writes into a bind mount. Truncating the file from the host while the container
# holds it open is NOT safe: the writer in the Docker VM can keep a stale offset and leave a NUL hole
# (measured: 588 MB in sc-06's trace file, 1.16 GB in sc-11's). So the collector is STOPPED (it closes
# and flushes its files) around every truncation and started again; the lab's exporter queues and
# retries meanwhile. The file being compressed is therefore never written to.
live_reset() {   # $1 = "start" | "end"
  docker stop -t 20 $COLL >/dev/null
  : > "$LIVE/logs.jsonl"; : > "$LIVE/traces.jsonl"
  local since; since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  docker start $COLL >/dev/null
  for _ in $(seq 1 60); do docker logs --since "$since" $COLL 2>&1 | grep -q "Everything is ready" && break; sleep 1; done
  local nip; nip=$(docker inspect $COLL --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}')
  if [ "$nip" != "$CIP" ]; then
    log "collector IP changed $CIP -> $nip; re-pointing the lab exporter"
    (cd "$RCALAB" && make otel OTLP_ENDPOINT="$nip:4317" OTLP_SIGNALS=traces,logs >/dev/null 2>&1)
    CIP=$nip
  fi
}

snapshot() {   # $1 = tag. Raw cluster state the meta step reads; small JSON files.
  local d=$OUT/cluster; mkdir -p "$d"
  $K get deploy,statefulset -o json > "$d/$1_workloads.json" 2>/dev/null
  kubectl --context $CTX get pods -A -o json > "$d/$1_pods.json" 2>/dev/null
  $K get maintenancejobs -o json > "$d/$1_maintenancejobs.json" 2>/dev/null
  kubectl --context $CTX get networkchaos -A -o json > "$d/$1_networkchaos.json" 2>/dev/null
  $CHECK "$SC" > "$d/$1_effect.json" 2>/dev/null || true
}

# ---------------------------------------------------------------- preflight
[ -e "$OUT/logs.jsonl.zst" ] || [ -e "$OUT/meta.json" ] && { echo "ABORT: $OUT already holds a capture"; exit 1; }
free_gb=$(df -g / | tail -1 | awk '{print $4}')
[ "$free_gb" -ge "$MIN_FREE_GB" ] || { echo "ABORT: only ${free_gb} GB free (< $MIN_FREE_GB)"; exit 1; }
[ "$(docker inspect -f '{{.State.Running}}' $COLL 2>/dev/null)" = true ] || { echo "ABORT: collector $COLL not running"; exit 1; }
CIP=$(docker inspect $COLL --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}')
$K get cm otel-collector-config -o jsonpath='{.data}' | grep -q "endpoint: $CIP:4317" \
  || { echo "ABORT: lab collector does not export to $CIP:4317"; exit 1; }
active=$($K get maintenancejobs -o jsonpath='{range .items[*]}{.metadata.name}={.status.phase}{"\n"}{end}' | grep -v '=Idle$' || true)
[ -z "$active" ] || { echo "ABORT: scenarios not idle: $active"; exit 1; }
for i in $(seq 1 60); do   # lab healthy: every app deployment fully available
  bad=$($K get deploy -l part-of=rca-lab -o jsonpath='{range .items[*]}{.metadata.name} {.spec.replicas} {.status.availableReplicas}{"\n"}{end}' | awk '$2!=$3')
  [ -z "$bad" ] && break; sleep 10; done
[ -z "$bad" ] || { echo "ABORT: lab unhealthy: $bad"; exit 1; }
if [ "$SC" != healthy ]; then
  phase=$($K get maintenancejob "$SC" -o jsonpath='{.status.phase}' 2>/dev/null)
  [ -n "$phase" ] || skip "no MaintenanceJob $SC on this cluster"
  $CHECK "$SC" >/dev/null 2>&1 && { echo "ABORT: $SC effect present before enabling"; exit 1; }
  CRDUR=$($K get maintenancejob "$SC" -o jsonpath='{.spec.duration}')
fi

mkdir -p "$OUT/cluster"
kubectl --context $CTX get nodes -o json > "$OUT/cluster/nodes.json"
kubectl --context $CTX version -o json > "$OUT/cluster/version.json" 2>/dev/null
$K get deploy load-generator -o json > "$OUT/cluster/load_generator.json"
$K get cm otel-collector-config -o json > "$OUT/cluster/lab_collector_configmap.json"
$K get cm otel-env -o json > "$OUT/cluster/otel_env_configmap.json"
docker inspect $COLL > "$OUT/cluster/host_collector_container.json"
[ "$SC" = healthy ] || $K get maintenancejob "$SC" -o json > "$OUT/cluster/maintenancejob.json"

# ---------------------------------------------------------------- capture
live_reset start
B0=$(now_ns); log "baseline ${BASE_S}s (free ${free_gb} GB)"
sleep "$BASE_S"; B1=$(now_ns)
snapshot baseline_end
F0=None; F1=None; R1=None; VER=None; STARTED=""; ENDED_BY=None; STILL=None
if [ "$SC" != healthy ]; then
  EN_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  $K patch maintenancejob "$SC" --type=merge -p '{"spec":{"enabled":true}}' >/dev/null
  log "enabled (CR duration $CRDUR)"
  for _ in $(seq 1 60); do
    STARTED=$($K logs deploy/maintenance-controller --since-time="$EN_ISO" 2>/dev/null \
              | grep '"starting run"' | grep "\"name\":\"$SC\"" | head -1 || true)
    [ -n "$STARTED" ] && break; sleep 2; done
  if [ -z "$STARTED" ]; then revert; skip "controller never logged 'starting run' within 120s of enabling"; fi
  F0=$(now_ns); log "starting run seen"
  for _ in $(seq 1 90); do
    if $CHECK "$SC" > "$OUT/cluster/fault_effect_first.json" 2>/dev/null; then VER=$(now_ns); break; fi
    ph=$($K get maintenancejob "$SC" -o jsonpath='{.status.phase}')
    [ "$ph" = Failed ] && break; sleep 2; done
  [ "$VER" = None ] && log "WARNING: effect NOT verified within 180s (capture kept, flagged)" \
                    || log "effect verified $(( (VER - F0) / 1000000000 ))s after run start"
  mid_done=0
  while :; do
    t=$(python3 -c "import time; print(int(time.time() - $F0/1e9))")
    [ "$t" -ge "$FAULT_S" ] && { ENDED_BY='"fault_s"'; break; }
    ph=$($K get maintenancejob "$SC" -o jsonpath='{.status.phase}')
    if { [ "$ph" = Idle ] || [ "$ph" = Reverting ]; } && [ "$t" -gt 30 ]; then ENDED_BY="\"cr_phase_$ph\""; log "CR left Active ($ph) at ${t}s"; break; fi
    if [ $mid_done = 0 ] && [ "$t" -ge $(( FAULT_S / 2 )) ]; then snapshot fault_mid; mid_done=1; fi
    sleep 5
  done
  $CHECK "$SC" > "$OUT/cluster/fault_effect_end.json" 2>/dev/null && STILL=True || STILL=False
  F1=$(now_ns); revert; log "disabled (effect present at end: $STILL)"
  for _ in $(seq 1 90); do [ "$($K get maintenancejob "$SC" -o jsonpath='{.status.phase}')" = Idle ] && break; sleep 2; done
  sleep "$REC_S"; R1=$(now_ns)
  snapshot recovery_end
fi
sleep 5   # let the collector flush its last batch
WD_STOPPED=False
[ "$(docker inspect -f '{{.State.Running}}' $COLL)" = true ] || { WD_STOPPED=True; log "WARNING: collector was not running at capture end (watchdog cap?)"; }
docker stop -t 20 $COLL >/dev/null          # closes + flushes the files: nothing writes while we read
zstd -T8 -6 -q -c "$LIVE/logs.jsonl" > "$OUT/logs.jsonl.zst" || log "WARNING: zstd logs rc=$?"
zstd -T8 -6 -q -c "$LIVE/traces.jsonl" > "$OUT/traces.jsonl.zst" || log "WARNING: zstd traces rc=$?"
zstd -q -t "$OUT/logs.jsonl.zst" && zstd -q -t "$OUT/traces.jsonl.zst" && ZOK=True || ZOK=False
RAW_LOG=$(stat -f %z "$LIVE/logs.jsonl"); RAW_TR=$(stat -f %z "$LIVE/traces.jsonl")
live_reset end
python3 - "$OUT/meta_raw.json" <<EOF
import json, sys
json.dump({"name": "$NAME", "scenario": "$SC", "format": "dataset-v1", "cluster_context": "$CTX",
           "baseline_s": $BASE_S, "fault_s": $FAULT_S, "recovery_s": $REC_S, "cr_duration": "${CRDUR:-}",
           "baseline_start_ns": $B0, "baseline_end_ns": $B1,
           "fault_start_ns": $F0, "fault_end_ns": $F1, "recovery_start_ns": $F1, "recovery_end_ns": $R1,
           "effect_verified_ns": $VER, "effect_present_at_end": $STILL, "fault_ended_by": $ENDED_BY,
           "controller_line": json.loads(json.dumps(r'''$STARTED''')),
           "raw_bytes": {"logs": $RAW_LOG, "traces": $RAW_TR}, "zstd_test_ok": $ZOK,
           "collector_stopped_before_end": $WD_STOPPED, "live_reset": "docker stop/start around truncation",
           "host_collector_ip": "$CIP"}, open(sys.argv[1], "w"), indent=1)
EOF
log "wrote $OUT ($(du -sh "$OUT" | cut -f1); raw logs $RAW_LOG B, traces $RAW_TR B)"
