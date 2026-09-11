#!/usr/bin/env bash
# Poll Ollama Cloud until the session usage limit lifts, then run the v2 matrix on cloud models.
#
# The 336-cell v1 run exhausted the account limit ("you (barun1024) have reached your session usage
# limit"). That is a transport failure, not an observation: those cells were never run, so resuming
# is finishing an unfinished run rather than re-rolling an unfavourable result.
#
# Usage:  scripts/await_cloud_and_run.sh [max_hours]
set -u
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
MAX_H="${1:-10}"
DEADLINE=$(( $(date +%s) + MAX_H * 3600 ))
LOG=/private/tmp/claude-501/-Users-daemon1024-play-tokentax/2af019f8-7bc7-48b4-9506-56996f85ff0d/scratchpad/cloud_watch.log

probe() {
  curl -s --max-time 60 -H "Authorization: Bearer $OLLAMA_API_KEY" -H 'Content-Type: application/json' \
    https://ollama.com/api/chat \
    -d '{"model":"gpt-oss:120b","messages":[{"role":"user","content":"ok"}],"stream":false,"options":{"num_predict":4}}'
}

echo "[$(date +%H:%M)] waiting for cloud limit to lift (max ${MAX_H}h)" | tee -a "$LOG"
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  r=$(probe)
  if ! printf '%s' "$r" | grep -q 'usage limit'; then
    echo "[$(date +%H:%M)] cloud available — starting v2 cloud run" | tee -a "$LOG"
    # Frontier models first. kimi-k3/glm-5.2 were the ones rate-limited hardest in v1, so they go
    # last and the run stays useful even if they fail again.
    .venv/bin/python scripts/run_nezha_matrix.py --tag v2 \
      --models gpt-oss:120b,qwen3.5:397b,glm-5.3,deepseek-v4.1-flash,minimax-m3,nemotron-3-ultra \
      --concurrency 3 >> "$LOG" 2>&1
    echo "[$(date +%H:%M)] cloud v2 run exited $?" | tee -a "$LOG"
    exit 0
  fi
  sleep 600
done
echo "[$(date +%H:%M)] gave up after ${MAX_H}h — cloud still limited" | tee -a "$LOG"
exit 1
