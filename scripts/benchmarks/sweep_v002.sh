#!/usr/bin/env bash
# v0.0.2 baseline sweep: single vs parallel_consensus (group A) over all three datasets,
# full datasets, seed=7, repeats=1, on Groq gpt-oss-20b (medium/8192, pinned in .env).
#
# Sequential on purpose: Groq's 250k tok/min cap is per-org, so concurrent jobs thrash each
# other's rate limit. Single is light (concurrency 8); consensus is token-heavy (concurrency 2,
# SDK backoff absorbs 429s). TruthfulQA uses --defer-judge (predictions only) — an independent
# Sonnet workflow grades them afterward (scripts.benchmarks.judge).
#
# Resumable: a stage whose result JSON already exists is SKIPPED, so a detached re-launch
# continues where it left off. Each finished stage appends one score line to SCORES (the live
# scoreboard) so progress is visible from disk, independent of any Claude session.
#
# Run detached (survives session end):
#   set -a && . ./.env && set +a && nohup bash scripts/benchmarks/sweep_v002.sh >/dev/null 2>&1 &
set -u
cd "$(dirname "$0")/../.." || exit 1

SEED=7
LOG=data/results/sweep_v002.log
SCORES=data/results/scores_v002.md
DONE=data/results/SWEEP_DONE
rm -f "$DONE"

score_of() {  # glob-pattern -> "92.6%" | "deferred (pending Sonnet judge)" | "(none)"
  python - "$1" <<'PY'
import sys, glob, os, json
fs = sorted(glob.glob(sys.argv[1]), key=os.path.getmtime)
if not fs:
    print("(none)"); raise SystemExit
r = json.load(open(fs[-1]))
s = r.get("score")
print("deferred (pending Sonnet judge)" if s is None else f"{s*100:.1f}%  (n={r['n']})")
PY
}

run() {  # label, glob (existing => skip), then python args
  local label="$1" glob="$2"; shift 2
  if compgen -G "$glob" >/dev/null; then
    echo "=== SKIP $label (result exists) ===" | tee -a "$LOG"
    return
  fi
  echo "=== $label  @ $(date '+%F %T') ===" | tee -a "$LOG"
  python -m scripts.benchmarks.run "$@" --seed "$SEED" --record 2>>"$LOG" | tee -a "$LOG"
  echo "- **$label** → $(score_of "$glob")  _( $(date '+%H:%M:%S') )_" | tee -a "$SCORES"
  echo "--- done: $label  @ $(date '+%F %T') ---" | tee -a "$LOG"
}

echo "##### v0.0.2 sweep START @ $(date '+%F %T') #####" | tee -a "$LOG"
{ echo; echo "### v0.0.2 baseline scoreboard ($(date '+%F %T'))"; echo "Groq gpt-oss-20b · medium · 8192 · seed=$SEED · group A · single vs framework"; echo; } >> "$SCORES"

run "math500 single"          "data/results/math500_single_*.json"                       --benchmark math500      --system single                       --concurrency 8
run "math500 framework/A"     "data/results/math500_parallel_consensus_A_*.json"         --benchmark math500      --system parallel_consensus --group A --concurrency 2
run "gpqa single"             "data/results/gpqa_diamond_single_*.json"                  --benchmark gpqa_diamond --system single                       --concurrency 8
run "gpqa framework/A"        "data/results/gpqa_diamond_parallel_consensus_A_*.json"    --benchmark gpqa_diamond --system parallel_consensus --group A --concurrency 2
run "truthfulqa single"       "data/results/truthfulqa_single_*.json"                    --benchmark truthfulqa   --system single                       --concurrency 8 --defer-judge
run "truthfulqa framework/A"  "data/results/truthfulqa_parallel_consensus_A_*.json"      --benchmark truthfulqa   --system parallel_consensus --group A --concurrency 2 --defer-judge

echo "##### v0.0.2 sweep END @ $(date '+%F %T') #####" | tee -a "$LOG"
touch "$DONE"
