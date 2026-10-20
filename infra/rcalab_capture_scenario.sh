#!/bin/bash
# Capture one rca-lab scenario: baseline, then a bounded fault segment, then revert. Writes
# data/rcalab/<scenario>/{logs.jsonl,traces.jsonl,meta.json} from the host collector's live files.
#
#   infra/rcalab_capture_scenario.sh <scenario> <culprit-service> <baseline_s> <fault_s>
#
# The live files are TRUNCATED at the start (the file exporter opens them O_APPEND, so writes
# continue at offset 0) and again after the copy, so no capture ever grows without bound. A separate
# watchdog stops the collector if a file passes its size cap.
#
# The fault window starts at the controller's "starting run" log line for this scenario, not at the
# kubectl patch: RCA_LAB_CAPTURE.md was retracted because a capture taken with NO scenario running was
# mistaken for a fault. If "starting run" does not appear, or the scenario-specific effect check below
# never passes, the script aborts, reverts, and writes nothing.
set -euo pipefail
SC=$1; CULPRIT=$2; BASE_S=$3; FAULT_S=$4
CTX=${CTX:-kind-rca-lab}
LIVE=${LIVE:-$HOME/tokentax-capture-v2}
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=$REPO/data/rcalab/$SC
K="kubectl --context $CTX -n default"
now_ns() { python3 -c 'import time; print(time.time_ns())'; }
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

effect_check() {   # exit 0 when the fault's mechanism is observably in place
  case "$SC" in
    sc-06) $K exec "$($K get pod -l "postgres-operator.crunchydata.com/role in (master,primary)" -o name | head -1)" -c database -- \
             psql -d products -tAc "select count(*) from pg_locks l join pg_class c on c.oid=l.relation
             where c.relname='products' and l.mode='AccessExclusiveLock' and l.granted" 2>/dev/null \
             | grep -E '^[0-9]+$' | grep -qv '^0$' ;;
    sc-04) $K exec mysql-pxc-0 -c pxc -- sh -c 'mysql -uroot -p"$(cat /etc/mysql/mysql-users-secret/root)" -N -e "select count(*) from information_schema.innodb_trx where trx_rows_locked>0" 2>/dev/null' \
             | grep -E '^[0-9]+$' | grep -qv '^0$' ;;
    sc-11) [ "$($K get deploy review-service -o jsonpath='{.spec.template.spec.containers[0].image}')" = \
             ghcr.io/coroot/rca-lab/review-service:1.2.0 ] && $K rollout status deploy/review-service --timeout=5s >/dev/null 2>&1 ;;
    sc-15) kubectl --context $CTX get networkchaos -A -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="AllInjected")].status}{"\n"}{end}' \
             2>/dev/null | grep -q True ;;
    sc-10) $K get pod -l app=recommendation-service -o jsonpath='{.items[*].spec.containers[0].image}' | grep -q ':1.1.0' ;;
    *) echo "no effect check for $SC" >&2; return 1 ;;
  esac
}

phase=$($K get maintenancejob "$SC" -o jsonpath='{.status.phase}')
[ "$phase" = Idle ] || { echo "ABORT: $SC phase is $phase, not Idle"; exit 1; }
if effect_check; then echo "ABORT: effect already present before enabling $SC"; exit 1; fi

mkdir -p "$LIVE"; : > "$LIVE/logs.jsonl"; : > "$LIVE/traces.jsonl"
B0=$(now_ns); log "baseline ${BASE_S}s"; sleep "$BASE_S"; B1=$(now_ns)

EN=$(now_ns); EN_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
$K patch maintenancejob "$SC" --type=merge -p '{"spec":{"enabled":true}}' >/dev/null
log "enabled $SC"

revert() { $K patch maintenancejob "$SC" --type=merge -p '{"spec":{"enabled":false}}' >/dev/null || true; }
started=""; for _ in $(seq 1 60); do
  started=$($K logs deploy/maintenance-controller --since-time="$EN_ISO" 2>/dev/null \
            | grep '"starting run"' | grep "\"$SC\"" | head -1 || true)
  [ -n "$started" ] && break; sleep 2; done
[ -n "$started" ] || { log "ABORT: no 'starting run' for $SC"; revert; exit 1; }
F0=$(now_ns); log "controller: $(echo "$started" | cut -c1-200)"

verified=""; for _ in $(seq 1 90); do
  if effect_check; then verified=$(now_ns); break; fi; sleep 2; done
[ -n "$verified" ] || { log "ABORT: effect never observed for $SC"; revert; exit 1; }
log "effect observed $(( (verified - F0) / 1000000000 ))s after run start"

sleep_s=$(python3 -c "import time; print(max(0, $F0/1e9 + $FAULT_S - time.time()))")
sleep "$sleep_s"; F1=$(now_ns)
still=$(effect_check && echo yes || echo no)
revert; log "disabled $SC (effect still present at end: $still)"
for _ in $(seq 1 90); do [ "$($K get maintenancejob "$SC" -o jsonpath='{.status.phase}')" = Idle ] && break; sleep 2; done
sleep 5   # let the collector flush the last batch
mkdir -p "$OUT"
cp "$LIVE/logs.jsonl" "$OUT/logs.jsonl"; cp "$LIVE/traces.jsonl" "$OUT/traces.jsonl"
: > "$LIVE/logs.jsonl"; : > "$LIVE/traces.jsonl"
cat > "$OUT/meta.json" <<EOF
{"scenario": "$SC", "culprit": "$CULPRIT", "cluster_context": "$CTX",
 "baseline_start_ns": $B0, "baseline_end_ns": $B1, "enabled_ns": $EN,
 "fault_start_ns": $F0, "effect_verified_ns": $verified, "fault_end_ns": $F1,
 "effect_present_at_end": "$still",
 "controller_line": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$started")}
EOF
log "wrote $OUT ($(du -sh "$OUT" | cut -f1))"
