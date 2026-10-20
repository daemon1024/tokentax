#!/bin/bash
# Stops the capture collector if any capture file exceeds its cap or host free disk falls too low.
D=$HOME/tokentax-capture-v2
TCAP=$((5000*1024*1024)); LCAP=$((400*1024*1024)); MINFREE_KB=$((6*1024*1024))
while true; do
  t=$(stat -f %z $D/traces.jsonl 2>/dev/null || echo 0); l=$(stat -f %z $D/logs.jsonl 2>/dev/null || echo 0)
  free=$(df -k / | tail -1 | awk '{print $4}')
  if [ "$t" -gt "$TCAP" ] || [ "$l" -gt "$LCAP" ] || [ "$free" -lt "$MINFREE_KB" ]; then
    echo "$(date -u +%FT%TZ) CAP HIT traces=$t logs=$l free_kb=$free -> stopping tokentax-capture2"
    docker stop tokentax-capture2
    sleep 60
  fi
  sleep 10
done
