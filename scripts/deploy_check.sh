#!/usr/bin/env bash
# make deploy-check: build the Docker image and run it the way Render's free
# instance would (0.1 CPU, 512 MB, PORT=10000), then check that it serves the
# frontend and the API, and time three backtest requests, one after another:
#
# - the run form's default (5 symbols over 2023, Conservative, with the
#   unmanaged baseline);
# - TradeDesk's run_backtest shape (1 symbol over the file's full range,
#   2020-2024, no risk layer, no baseline);
# - the largest run the default caps allow (10 symbols over 2020-2024, the
#   1,827-day maximum, Conservative, with the baseline).
#
# For each it records how slowly /health answers while the run holds the CPU.
# SQLite inside the container, so no database is needed. Stops and removes
# its container when done.
#
# The timings depend on the host's CPU, so they show what to expect, not what
# Render will measure.
set -euo pipefail

IMAGE=${IMAGE:-quant-deploy-check}
NAME=${NAME:-quant-deploy-check}
PORT=${DEPLOY_CHECK_PORT:-18090}
BASE="http://127.0.0.1:${PORT}"
DEFAULT_RUN='{"strategy_name":"Moving Average Crossover","risk_config_name":"Conservative","start_date":"2023-01-01","end_date":"2023-12-31","initial_capital":100000,"symbols":["AAPL","AMZN","GOOGL","JPM","MSFT"],"parameters":{"fast_period":20,"slow_period":50},"compare_to_baseline":true,"data_source":"synthetic"}'
ONE_SYMBOL_RUN='{"strategy_name":"Moving Average Crossover","risk_config_name":"No Risk Management","start_date":"2020-01-01","end_date":"2024-12-31","initial_capital":100000,"symbols":["AAPL"],"data_source":"synthetic"}'
LARGEST_RUN='{"strategy_name":"Moving Average Crossover","risk_config_name":"Conservative","start_date":"2020-01-01","end_date":"2024-12-31","initial_capital":100000,"symbols":["AAPL","AMZN","GOOGL","JPM","MSFT","META","NFLX","NVDA","TSLA","V"],"compare_to_baseline":true,"data_source":"synthetic"}'
TMP=$(mktemp -d)
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT

docker build -q -t "$IMAGE" . >/dev/null
docker run -d --name "$NAME" --cpus 0.1 --memory 512m -e PORT=10000 \
  -e DATABASE_URL=sqlite:////tmp/quant.db -p "127.0.0.1:${PORT}:10000" "$IMAGE" >/dev/null

start=$(date +%s)
until curl -sf -o /dev/null "$BASE/health"; do
  if [ $(( $(date +%s) - start )) -gt 180 ]; then echo "not ready after 180 s"; docker logs "$NAME"; exit 1; fi
  sleep 1
done
echo "ready (migrations, seed, gunicorn) after $(( $(date +%s) - start )) s"

index=$(curl -s -w '\n%{http_code}' "$BASE/")
[ "$(tail -n1 <<<"$index")" = 200 ] && grep -q '<div id="root">' <<<"$index" || { echo "/ did not serve the frontend"; exit 1; }
echo "/: 200, the React app"
curl -sf "$BASE/api/data" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("/api/data: {}, {} symbols, limits {}".format(d["source"], len(d["symbols"]), d["limits"]))'

# timed_run LABEL BODY: POST one backtest, polling /health every 2 s until it answers
timed_run() {
  curl -s -o "$TMP/run.json" -w '%{http_code} %{time_total}\n' -X POST "$BASE/api/backtest/" \
    -H 'Content-Type: application/json' -d "$2" > "$TMP/run.status" &
  local run=$!
  : > "$TMP/health"
  while kill -0 "$run" 2>/dev/null; do
    curl -s -o /dev/null -w '%{http_code} %{time_total}\n' --max-time 10 "$BASE/health" >> "$TMP/health" || echo "000 10" >> "$TMP/health"
    sleep 2
  done
  wait "$run"
  read -r status seconds < "$TMP/run.status"
  echo "$1: HTTP ${status} in ${seconds} s"
  python3 - "$TMP/health" <<'EOF'
import sys
rows = [line.split() for line in open(sys.argv[1]) if line.strip()]
ok = sum(1 for code, _ in rows if code == '200')
slowest = f', slowest {max(float(t) for _, t in rows):.2f} s' if rows else ''
print(f'  /health during the run: {ok} of {len(rows)} checks answered 200{slowest}')
EOF
}

timed_run "default run (5 symbols, 2023, with baseline)" "$DEFAULT_RUN"
timed_run "1 symbol, 2020-2024, no baseline (TradeDesk's request)" "$ONE_SYMBOL_RUN"
timed_run "largest allowed (10 symbols, 2020-2024, with baseline)" "$LARGEST_RUN"
docker stats --no-stream --format 'memory after the runs: {{.MemUsage}}' "$NAME"
