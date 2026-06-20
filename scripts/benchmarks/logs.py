"""Logging that coexists with a tqdm progress bar.

The orchestrator emits verbose ``DECISION`` records on the ``openai_420`` logger (see
``openai_420/trace.py``); a plain ``StreamHandler`` would shred an active tqdm bar. Routing
every record through ``tqdm.write`` keeps the bar intact. The harness's own milestones go to
the ``scripts.benchmarks`` logger so progress narration and agent traces share one stream.

DECISION records are off by default (one eval question fans out to dozens) — ``--verbose``
raises the ``openai_420`` logger to INFO to see them.
"""

from __future__ import annotations

import logging

from tqdm import tqdm

LOG = logging.getLogger("scripts.benchmarks")


class TqdmLoggingHandler(logging.Handler):
    """Emit each record via ``tqdm.write`` so it prints above the live bar, not through it."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record))
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)


def configure(*, verbose: bool) -> logging.Logger:
    """Wire both loggers to a tqdm-safe handler; return the harness logger. Idempotent."""
    handler = TqdmLoggingHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))

    harness = logging.getLogger("scripts.benchmarks")
    harness.handlers[:] = [handler]
    harness.setLevel(logging.INFO)
    harness.propagate = False

    orchestration = logging.getLogger("openai_420")
    orchestration.handlers[:] = [handler]
    orchestration.setLevel(logging.INFO if verbose else logging.WARNING)
    orchestration.propagate = False

    return harness
