"""A tiny Hugging Face datasets-server client (PRINCIPLES-style: one job, no heavy deps).

We deliberately do NOT pull in the ``datasets`` library — the project keeps its runtime to
``openai`` alone. The datasets-server ``/rows`` endpoint serves any preview-enabled dataset
as plain JSON over HTTP, which ``requests`` can page through directly. Gated datasets (GPQA)
work the same way once an ``HF_TOKEN`` is present and the user has accepted the dataset terms.
"""

from __future__ import annotations

import os

import requests

_ROWS_URL = "https://datasets-server.huggingface.co/rows"
_PAGE = 100  # the endpoint caps `length` at 100 rows per request
_TIMEOUT = 60


class GatedDatasetError(RuntimeError):
    """Raised when a dataset needs auth the caller hasn't provided — carries guidance."""


def fetch_rows(
    dataset: str,
    config: str,
    split: str,
    *,
    limit: int | None = None,
) -> list[dict]:
    """Return the ``row`` payloads for ``dataset/config/split``, paging until exhausted.

    Reads ``HF_TOKEN`` (or ``HUGGINGFACE_TOKEN``) from the environment when present so gated
    datasets resolve; raises ``GatedDatasetError`` with a fix-it message on 401/403.
    """
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    rows: list[dict] = []
    offset = 0
    while True:
        want = _PAGE if limit is None else min(_PAGE, limit - len(rows))
        if want <= 0:
            break
        params = {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": want,
        }
        response = requests.get(
            _ROWS_URL, params=params, headers=headers, timeout=_TIMEOUT
        )
        if response.status_code in (401, 403):
            raise GatedDatasetError(
                f"{dataset} is gated. Accept its terms at "
                f"https://huggingface.co/datasets/{dataset} and set HF_TOKEN "
                f"(https://huggingface.co/settings/tokens) before downloading."
            )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("rows", [])
        if not batch:
            break
        rows.extend(entry["row"] for entry in batch)
        total = payload.get("num_rows_total")
        offset += len(batch)
        if total is not None and offset >= total:
            break
    return rows
