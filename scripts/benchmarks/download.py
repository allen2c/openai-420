"""Download + normalize benchmarks into ``data/<name>.jsonl`` (idempotent).

    python -m scripts.benchmarks.download all
    python -m scripts.benchmarks.download math500 truthfulqa --force --limit 50

Already-present datasets are skipped unless ``--force``. A gated source (GPQA) that lacks an
``HF_TOKEN`` is reported with a fix-it message and skipped, so the other downloads still land.
Progress and per-dataset counts narrate through the tqdm-integrated harness logger.
"""

from __future__ import annotations

import argparse
import json

from tqdm import tqdm

from scripts.benchmarks.hf import GatedDatasetError, fetch_rows
from scripts.benchmarks.logs import LOG, configure
from scripts.benchmarks.paths import DATA_DIR, dataset_path
from scripts.benchmarks.registry import BENCHMARKS, Benchmark


def download(bench: Benchmark, *, force: bool, limit: int | None) -> int:
    """Fetch, normalize, and write one benchmark; return the number of samples written."""
    out = dataset_path(bench.name)
    if out.exists() and not force:
        count = sum(1 for _ in out.open())
        LOG.info("%s: present (%d rows), skipping — use --force", bench.name, count)
        return count
    rows = fetch_rows(bench.dataset, bench.config, bench.split, limit=limit)
    samples = [s for i, row in enumerate(rows) if (s := bench.normalize(row, i))]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for sample in samples:
            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
    note = (
        ""
        if (limit or len(samples) == bench.expected)
        else f" [!] expected {bench.expected}"
    )
    LOG.info("%s: wrote %d samples → %s%s", bench.name, len(samples), out, note)
    return len(samples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download eval benchmarks into data/.")
    parser.add_argument(
        "names",
        nargs="*",
        default=["all"],
        help=f"benchmarks to fetch, or 'all' ({', '.join(BENCHMARKS)})",
    )
    parser.add_argument("--force", action="store_true", help="re-download if present")
    parser.add_argument(
        "--limit", type=int, default=None, help="cap rows (smoke testing)"
    )
    args = parser.parse_args(argv)
    configure(verbose=False)

    chosen = list(BENCHMARKS) if "all" in args.names else args.names
    unknown = [n for n in chosen if n not in BENCHMARKS]
    if unknown:
        parser.error(f"unknown benchmark(s): {', '.join(unknown)}")

    failures = 0
    for name in tqdm(chosen, desc="download", unit="set"):
        try:
            download(BENCHMARKS[name], force=args.force, limit=args.limit)
        except GatedDatasetError as exc:
            failures += 1
            LOG.warning("%s: SKIPPED — %s", name, exc)
        # One bad source must not abort the others or dump a traceback.
        except Exception as exc:
            failures += 1
            LOG.warning("%s: FAILED — %s", name, exc)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
