"""The benchmark registry: where each dataset lives and how to normalize one row.

Every benchmark maps its raw rows onto ONE schema so the downloader, scorer, and runner
never special-case a source:

    {id, benchmark, question, answer, grading, meta}

``grading`` is one of ``math`` | ``mc`` | ``judge`` and selects the scorer. ``meta`` carries
the difficulty bucket (level / domain / category) that the runner reports a breakdown over,
plus anything the judge needs. GPQA's four options are shuffled by a hash of the record id so
the correct letter is reproducible across runs without leaking position.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

_LETTERS = "ABCD"


@dataclass(frozen=True)
class Benchmark:
    """One dataset source plus the function that turns a raw row into a sample dict."""

    name: str
    dataset: str
    config: str
    split: str
    grading: str
    normalize: Callable[[dict, int], dict | None]
    expected: int  # sanity-check count; a mismatch warns but does not fail


def make_sample(
    benchmark: str, idx: int, question: str, answer: str, grading: str, meta: dict
) -> dict:
    return {
        "id": f"{benchmark}-{idx}",
        "benchmark": benchmark,
        "question": question,
        "answer": answer,
        "grading": grading,
        "meta": meta,
    }


def _math500(row: dict, idx: int) -> dict:
    return make_sample(
        "math500",
        idx,
        question=row["problem"],
        answer=row["answer"],
        grading="math",
        meta={"level": row.get("level"), "subject": row.get("subject")},
    )


def _gpqa_diamond(row: dict, idx: int) -> dict:
    correct = row["Correct Answer"]
    options = [
        correct,
        row["Incorrect Answer 1"],
        row["Incorrect Answer 2"],
        row["Incorrect Answer 3"],
    ]
    order = _deterministic_order(row.get("Record ID", str(idx)))
    shuffled = [options[i] for i in order]
    letter = _LETTERS[shuffled.index(correct)]
    block = "\n".join(f"{lab}) {text}" for lab, text in zip(_LETTERS, shuffled))
    return make_sample(
        "gpqa_diamond",
        idx,
        question=f"{row['Question']}\n\n{block}",
        answer=letter,
        grading="mc",
        meta={"domain": row.get("High-level domain"), "choices": shuffled},
    )


def _truthfulqa(row: dict, idx: int) -> dict:
    return make_sample(
        "truthfulqa",
        idx,
        question=row["question"],
        answer=row["best_answer"],
        grading="judge",
        meta={
            "category": row.get("category"),
            "correct_answers": row.get("correct_answers", []),
            "incorrect_answers": row.get("incorrect_answers", []),
        },
    )


BENCHMARKS: dict[str, Benchmark] = {
    "math500": Benchmark(
        name="math500",
        dataset="HuggingFaceH4/MATH-500",
        config="default",
        split="test",
        grading="math",
        normalize=_math500,
        expected=500,
    ),
    "gpqa_diamond": Benchmark(
        name="gpqa_diamond",
        dataset="Idavidrein/gpqa",
        config="gpqa_diamond",
        split="train",
        grading="mc",
        normalize=_gpqa_diamond,
        expected=198,
    ),
    "truthfulqa": Benchmark(
        name="truthfulqa",
        dataset="truthfulqa/truthful_qa",  # canonical `truthful_qa` was renamed under a namespace
        config="generation",
        split="validation",
        grading="judge",
        normalize=_truthfulqa,
        expected=817,
    ),
}


def _deterministic_order(seed: str) -> list[int]:
    """A fixed permutation of [0,1,2,3] derived from ``seed`` (Fisher-Yates on a hash)."""
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    order = [0, 1, 2, 3]
    for i in range(3, 0, -1):
        digest, j = divmod(digest, i + 1)
        order[i], order[j] = order[j], order[i]
    return order
