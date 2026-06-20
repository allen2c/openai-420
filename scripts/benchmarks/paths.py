"""Where files live. One place so the downloader, runner, and analyzer agree."""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BASELINES = (
    DATA_DIR / "baselines.yaml"
)  # canonical table, maintained by hand (no auto-promote)
RESULTS_DIR = DATA_DIR / "results"  # one immutable JSON per --record run (the history)


def dataset_path(name: str) -> Path:
    """The local JSONL for a downloaded benchmark (gitignored)."""
    return DATA_DIR / f"{name}.jsonl"
