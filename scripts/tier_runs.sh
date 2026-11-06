#!/bin/sh
# Main tier runs: seed outermost, then task, then tier. Stops at $14.00 reported cost.
# Smoke test (seed 999, 0.015 USD) counts toward the total.
total=0.015; : > evidence/tier-runs.log
for seed in 101 102 103; do
 for task in tier-incident-triage tier-bulk-entry tier-config-rollout tier-meeting-slot tier-moving-target tier-file-triage; do
  for model in haiku sonnet opus; do
   out=$(uv run scripts/benchmark.py --suite tiers --only $task --seed $seed --model $model --budget 0.75 2>&1)
   dir=$(echo "$out" | grep -o 'artifacts/benchmark/[0-9a-f-]*' | head -1)
   cost=$(python3 -c "import json;print(json.load(open('$dir/summary.json'))['summary']['total_cost_usd'])")
   api=$(python3 -c "import json;print(json.load(open('$dir/summary.json'))['summary']['invalid_api_error'])")
   total=$(python3 -c "print($total+$cost)")
   echo "$seed $task $model $dir cost=$cost total=$total api=$api" >> evidence/tier-runs.log
   [ "$api" != "[]" ] && { echo "API ERROR STOP" >> evidence/tier-runs.log; exit 0; }
   python3 -c "import sys;sys.exit(0 if $total<14 else 1)" || { echo "BUDGET STOP" >> evidence/tier-runs.log; exit 0; }
  done
 done
done
echo COMPLETE >> evidence/tier-runs.log
