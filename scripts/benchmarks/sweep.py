"""Effort×dataset score-profile sweep for the LOCAL Ollama roster (v0.0.5 baseline groundwork).

Builds the per-(model, dataset, effort) single-model score profile that later framework runs
compare against — i.e. each model's effort sweet spot on each dataset (PRINCIPLES Law 13). It is
NOT the framework eval; every cell is ``--system single``.

Design choices, all learned the hard way (see memory):
- Each cell is one provider-style inference config. mistral-small3.2 rejects ``reasoning_effort``
  ("does not support thinking"), so its config simply omits the key — the effort axis is per-model,
  not global. The reasoning models sweep none/low/medium; HIGH is skipped (it self-truncates on hard
  sets at 32k and costs >=4x the tokens for ~+3pp — see aime-effort-nonmonotonic).
- model-OUTER ordering keeps one model resident in Ollama's VRAM across its whole row (Ollama
  serializes and reloads on model switch, so column-major would thrash).
- Every cell ``--record``s; the sweep is RESUMABLE — a cell whose (provider, benchmark, model,
  effort, n) already exists in data/results is skipped, so a crash at hour 8 resumes cleanly.
- Continue-on-error: one bad cell logs and the sweep moves on; it never aborts the row.

Run detached (survives the session):
    nohup poetry run python -m scripts.benchmarks.sweep > data/results/sweep.log 2>&1 &
Progress (one line per cell) lands in data/results/sweep_progress.log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from glob import glob

from scripts.benchmarks.paths import RESULTS_DIR

OLLAMA_BASE_URL = "http://localhost:11434/v1"
TOKEN_BUDGET = "32768"
SEED = "0"
CONCURRENCY = "2"  # Ollama serializes requests; high concurrency just queues
EFFORTS = ["none", "low", "medium"]  # high excluded: truncates + token-hungry on hard sets

# Each model carries its publisher-recommended sampling params (verified, see .env.example). A model
# with reasoning support sweeps EFFORTS; mistral has effort=[None] (one cell, no reasoning_effort).
MODELS = [
    {"model": "gpt-oss:20b", "temperature": "1.0", "top_p": "1.0", "efforts": EFFORTS},
    {"model": "nemotron-3-nano:30b", "temperature": "1.0", "top_p": "1.0", "efforts": EFFORTS},
    {"model": "qwen3.6:35b", "temperature": "1.0", "top_p": "0.95", "efforts": EFFORTS},
    {"model": "mistral-small3.2", "temperature": "0.15", "top_p": None, "efforts": [None]},
]

# (benchmark, limit) — aime is small enough to run whole; the rest take a stratified profile sample.
DATASETS = [
    ("aime", "90"),
    ("gpqa_diamond", "100"),
    ("math500", "100"),
]

PROGRESS_LOG = str(RESULTS_DIR / "sweep_progress.log")


def _completed_keys() -> set[tuple]:
    """Keys of cells already recorded, so a resumed sweep skips them. A key is
    (provider, benchmark, model, effort, n) read from each result file's fingerprint."""
    done = set()
    for path in glob(str(RESULTS_DIR / "*.json")):
        try:
            d = json.load(open(path))
        except (json.JSONDecodeError, OSError):
            continue
        if d.get("system") != "single":
            continue
        inf = d.get("inference", {})
        params = inf.get("params", {}) or {}
        done.add(
            (
                inf.get("provider"),
                d.get("benchmark"),
                inf.get("model"),
                params.get("reasoning_effort"),  # None for mistral / unset
                d.get("n"),
            )
        )
    return done


def _log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a") as fh:
        fh.write(line + "\n")


def _cell_env(model: dict, effort: str | None) -> dict:
    """A clean per-cell environment for run.py's single-model path: pin this model's endpoint and
    params, drop OPENAI_PROVIDERS (homogeneous run), and set or REMOVE reasoning_effort."""
    env = dict(os.environ)
    env.pop("OPENAI_PROVIDERS", None)  # else run.py records it as heterogeneous
    env["OPENAI_BASE_URL"] = OLLAMA_BASE_URL
    env["OPENAI_API_KEY"] = "dummy"
    env["OPENAI_MODEL"] = model["model"]
    env["OPENAI_TEMPERATURE"] = model["temperature"]
    env["OPENAI_MAX_COMPLETION_TOKENS"] = TOKEN_BUDGET
    if model["top_p"] is not None:
        env["OPENAI_TOP_P"] = model["top_p"]
    else:
        env.pop("OPENAI_TOP_P", None)
    if effort is not None:
        env["OPENAI_REASONING_EFFORT"] = effort
    else:
        env.pop("OPENAI_REASONING_EFFORT", None)  # mistral rejects the key entirely
    return env


def _run_cell(model: dict, effort: str | None, benchmark: str, limit: str) -> None:
    tag = f"{model['model']} effort={effort or '-'} {benchmark} n={limit}"
    _log(f"START  {tag}")
    cmd = [
        sys.executable, "-m", "scripts.benchmarks.run",
        "--benchmark", benchmark, "--system", "single",
        "--limit", limit, "--seed", SEED,
        "--concurrency", CONCURRENCY, "--record",
    ]
    started = time.time()
    proc = subprocess.run(
        cmd, env=_cell_env(model, effort), capture_output=True, text=True
    )
    mins = (time.time() - started) / 60
    score = next(
        (ln.strip() for ln in proc.stdout.splitlines() if "→" in ln and "%" in ln), "?"
    )
    if proc.returncode != 0:
        _log(f"FAIL   {tag} ({mins:.1f}m) rc={proc.returncode} :: {proc.stderr.strip()[-300:]}")
    else:
        _log(f"DONE   {tag} ({mins:.1f}m) :: {score}")


def main() -> int:
    done = _completed_keys()
    cells = [
        (m, e, b, lim)
        for m in MODELS          # model-outer: keep VRAM warm across the row
        for b, lim in DATASETS
        for e in m["efforts"]
    ]
    _log(f"SWEEP start: {len(cells)} cells, {len(done)} already recorded")
    for model, effort, benchmark, limit in cells:
        key = ("ollama", benchmark, model["model"], effort, int(limit))
        if key in done:
            _log(f"SKIP   {model['model']} effort={effort or '-'} {benchmark} n={limit} (recorded)")
            continue
        try:
            _run_cell(model, effort, benchmark, limit)
        except Exception as exc:  # never let one cell abort the sweep
            _log(f"ERROR  {model['model']} {benchmark}: {exc!r}")
    _log("SWEEP done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
