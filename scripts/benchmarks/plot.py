"""Bar chart of mean±std accuracy per difficulty bucket, grouped by config, over repeats.

    python -m scripts.benchmarks.plot data/results/math500_single_*.json data/results/math500_parallel_consensus_*.json

Each result file is one repeat. Files are grouped by ``system[/group]@provider``; within a
group the repeats give the mean (bar height) and std (error bar). Buckets are the benchmark's
difficulty levels (plus an ``overall`` column), so you see where a system wins and how much
the temperature-driven spread is. Writes a PNG under ``data/results/`` and prints its path.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime

import matplotlib

matplotlib.use("Agg")  # headless: render to file, never open a window
import matplotlib.pyplot as plt  # noqa: E402

from scripts.benchmarks.paths import RESULTS_DIR  # noqa: E402


def load_grouped(paths: list[str]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for path in paths:
        run = json.loads(open(path, encoding="utf-8").read())
        groups[_config_label(run)].append(run)
    return groups


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot mean±std accuracy over repeats.")
    parser.add_argument("results", nargs="+", help="result JSON files (one per repeat)")
    parser.add_argument("--out", default=None, help="output PNG path")
    parser.add_argument("--title", default=None)
    args = parser.parse_args(argv)

    groups = load_grouped(args.results)
    benchmark = next(iter(groups.values()))[0]["benchmark"]
    buckets = sorted(
        {b for runs in groups.values() for r in runs for b in r["breakdown"]}
    )
    categories = buckets + ["overall"]
    labels = list(groups)

    fig, ax = plt.subplots(figsize=(max(7.0, len(categories) * 1.3), 5))
    width = 0.8 / len(labels)
    for i, label in enumerate(labels):
        means, stds = _series(groups[label], categories)
        offsets = [x + i * width for x in range(len(categories))]
        ax.bar(
            offsets,
            means,
            width,
            yerr=stds,
            capsize=3,
            label=f"{label} (K={len(groups[label])})",
        )

    ax.set_xticks([x + width * (len(labels) - 1) / 2 for x in range(len(categories))])
    ax.set_xticklabels(categories, rotation=30, ha="right")
    ax.set_ylabel("accuracy (%)")
    ax.set_ylim(0, 100)
    ax.set_title(args.title or f"{benchmark} — mean ± std over repeats")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    out = args.out or str(
        RESULTS_DIR / f"plot_{benchmark}_{datetime.now():%Y%m%d-%H%M%S}.png"
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")
    return 0


def _config_label(run: dict) -> str:
    tag = run["system"] + (f"/{run['group']}" if run.get("group") else "")
    provider = (run.get("inference") or {}).get("provider", "?")
    return f"{tag}@{provider}"


def _series(runs: list[dict], categories: list[str]) -> tuple[list[float], list[float]]:
    """Mean and std (as percentages) per category across the repeats."""
    per_bucket: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        for bucket, value in run["breakdown"].items():
            per_bucket[bucket].append(value)
    overall = [run["score"] for run in runs]

    means, stds = [], []
    for category in categories:
        vals = overall if category == "overall" else per_bucket.get(category, [])
        means.append(100 * statistics.mean(vals) if vals else 0.0)
        stds.append(100 * statistics.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds


if __name__ == "__main__":
    raise SystemExit(main())
