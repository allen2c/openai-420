# Benchmark eval harness

Formal, reproducible evaluation of the `single` baseline vs the `parallel_consensus`
orchestrator over standard benchmarks. Everything is async; every run carries a
reproducible signature and per-question detail.

## Benchmarks

| name           | size | grading | difficulty buckets |
|----------------|------|---------|--------------------|
| `math500`      | 500  | `math_verify` (objective) | level 1–5 |
| `gpqa_diamond` | 198  | MC letter (objective)     | high-level domain |
| `truthfulqa`   | 817  | LLM judge                 | category |

## Flow

```bash
# 1. download → data/<name>.jsonl  (gitignored; GPQA needs HF_TOKEN + accepted terms)
python -m scripts.benchmarks.download all

# 2. run a system; --record saves an immutable result JSON under data/results/
python -m scripts.benchmarks.run --benchmark math500 --system single \
    --limit 100 --seed 7 --repeats 5 --record
python -m scripts.benchmarks.run --benchmark math500 --system parallel_consensus \
    --group A --limit 100 --seed 7 --repeats 5 --concurrency 2 --record

# 3. paired significance + plot
python -m scripts.benchmarks.analyze data/results/<single>.json data/results/<consensus>.json
python -m scripts.benchmarks.plot data/results/math500_*rep*.json
```

## Baseline scheme

- **Reproducible signature** on every run: `code_version` (git sha), `sample`
  (scheme + n + seed + `ids_hash`), and `inference` (provider/endpoint/model). Two runs are
  *paired* iff their `ids_hash` matches; an Ollama score and a Groq score never conflate.
- **Stratified sampling** (`--sample stratified`, default) draws equal-per-bucket so the hard
  tail is present even at small `--limit`. `--seed` pins the exact question set.
- **Repeats** (`--repeats K`): sampling temperature is never set (PRINCIPLES Law 13), so scores
  vary run to run. K repeats on the same questions give mean±std; `plot.py` draws the error bars.
- **Two layers**: `data/results/*.json` are immutable per-run history (with per-question
  `items` carrying `extracted`+`gold` for grading audits). `data/baselines.yaml` is the
  canonical current-best table, **maintained by hand** (no auto-promote).
- **Significance**: `analyze.py` runs a paired McNemar (fixed/broke, exact binomial p) over two
  result files. Prefer it (or the per-repeat delta) over eyeballing error bars.

## Notes

- Groq's `gpt-oss-20b` is capped at **250k tokens/min** (org limit). Consensus is token-heavy,
  so use low `--concurrency` (≈2) to stay under the wall, and run long sweeps in the background.
  Ollama has no such cap (slower per call, but unlimited throughput).
- math grading wraps the gold as LaTeX (`$...$`) before `math_verify.parse` — bare `parse`
  silently misses ~10% of clean golds.

## v0.0.2 goals

1. **Validate + harden each dataset's eval** so all three grade reliably:
   - `math500` — math_verify parse/extraction edge cases (currency, intervals, degrees — done;
     watch for new ones via the `extracted`/`gold` audit).
   - `gpqa_diamond` — confirm MC letter extraction on real consensus outputs.
   - `truthfulqa` — wire the judge (planned: a Sonnet subagent) and validate it.
2. **Full-dataset sweep of all four groups** (`roles`, `A`, `B`, `C`) — single vs consensus,
   with mean±std and McNemar, to find the best epistemology team.
3. Stabilize each dataset's eval *before* the full sweep.
