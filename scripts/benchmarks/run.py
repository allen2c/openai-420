"""Run a system over a benchmark, score it, print the result (optionally save it).

    python -m scripts.benchmarks.run --benchmark math500 --system single --limit 50
    python -m scripts.benchmarks.run --benchmark math500 --system parallel_consensus --group A --limit 50
    python -m scripts.benchmarks.run --benchmark truthfulqa --system single --record

Two systems share one ``query -> answer`` interface:

- ``single``             — one model call; the reference baseline these benchmarks measure against.
- ``parallel_consensus`` — the multi-agent orchestrator, with ``--group`` selecting the roster.

A run is identified by a reproducible signature — model, the ``sample`` (scheme + n + seed +
ids_hash), and ``code_version`` (git sha) — so two runs can be proven paired (same ids_hash)
and compared across time (same sha). ``--sample stratified`` draws equal-per-bucket so hard
items are represented even at small ``--limit``.

Everything is async: questions run concurrently under a semaphore, a tqdm bar tracks
completion, and logging routes through it. ``--record`` saves the run (signature, score, and
per-question ``items``) as an immutable JSON under ``data/results/`` — the experiment history.
The canonical ``data/baselines.yaml`` is maintained by hand; copy the numbers you trust.
``analyze.py`` runs a paired McNemar test over two result files.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import statistics
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import openai
from tqdm import tqdm

from openai_420.orchestrators.parallel_consensus import ParallelConsensusOrchestrator
from openai_420.roster import GROUPS
from scripts.benchmarks import score as scoring
from scripts.benchmarks.logs import LOG, configure
from scripts.benchmarks.paths import RESULTS_DIR, dataset_path

_FORMAT_INSTRUCTION = {
    "math": "\n\nSolve it, then give the final answer alone inside \\boxed{}.",
    "mc": "\n\nThink it through, then end with `Answer: <letter>` (one of A, B, C, D).",
    "judge": "\n\nAnswer truthfully and concisely.",
}
_SINGLE_SYSTEM = "You are a careful expert. Answer the user's question."


def load_samples(benchmark: str) -> list[dict]:
    path = dataset_path(benchmark)
    if not path.exists():
        raise SystemExit(
            f"{path} missing — run `python -m scripts.benchmarks.download {benchmark}` first."
        )
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def select_samples(
    samples: list[dict], limit: int | None, scheme: str, seed: int
) -> list[dict]:
    """Pick the subset to evaluate. ``stratified`` draws ~equally across difficulty buckets
    (round-robin over a seeded shuffle) so the hard tail is present even at small ``limit``.
    """
    if limit is None or limit >= len(samples):
        return samples
    if scheme == "head":
        return samples[:limit]
    buckets: dict[str, list[dict]] = {}
    for sample in samples:
        buckets.setdefault(_bucket(sample), []).append(sample)
    rng = random.Random(seed)
    for pool in buckets.values():
        rng.shuffle(pool)
    order = sorted(buckets)
    chosen: list[dict] = []
    while len(chosen) < limit and any(buckets[b] for b in order):
        for key in order:
            if buckets[key]:
                chosen.append(buckets[key].pop())
            if len(chosen) >= limit:
                break
    return chosen


def client_from_env() -> tuple[openai.AsyncOpenAI, str, dict]:
    model = os.environ.get("OPENAI_MODEL")
    if not model:
        raise SystemExit("OPENAI_MODEL is not set (see .env).")
    base_url = os.environ.get("OPENAI_BASE_URL")
    # High max_retries so Groq's 250k tokens/min limit (consensus is token-heavy) throttles the
    # run via backoff instead of killing it — the SDK honors retry-after on each 429.
    client = openai.AsyncOpenAI(
        base_url=base_url,
        api_key=os.environ.get("OPENAI_API_KEY"),
        max_retries=16,
    )
    return client, model, inference_fingerprint(base_url, model)


def inference_fingerprint(base_url: str | None, model: str) -> dict:
    """Who actually served the tokens — so an Ollama score is never compared to a Groq one.

    The same model id (``gpt-oss-20b``) served by local Ollama (MXFP4) vs Groq is a different
    quantization and serving stack, so it can score differently; the provider tag pins it.
    """
    host = urlparse(base_url).netloc if base_url else ""
    provider = (
        "ollama"
        if ("localhost" in host or "11434" in host)
        else (
            "groq"
            if "groq" in host
            else "openai" if ("openai.com" in host or not host) else host or "unknown"
        )
    )
    return {"provider": provider, "endpoint": host or "api.openai.com", "model": model}


async def answer_single(client: openai.AsyncOpenAI, model: str, sample: dict) -> str:
    prompt = sample["question"] + _FORMAT_INSTRUCTION[sample["grading"]]
    # No temperature/top_p — provider default by design (PRINCIPLES Law 13).
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SINGLE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content or ""


async def answer_consensus(
    client: openai.AsyncOpenAI, model: str, sample: dict, group: str, rounds: int
) -> str:
    orchestrator = ParallelConsensusOrchestrator(
        client=client,
        model=model,
        specialist_specs=GROUPS[group],
        max_rounds=rounds,
    )
    return await orchestrator.run(
        sample["question"] + _FORMAT_INSTRUCTION[sample["grading"]]
    )


async def evaluate(args: argparse.Namespace) -> int:
    configure(verbose=args.verbose)
    pool = load_samples(args.benchmark)
    samples = select_samples(pool, args.limit, args.sample, args.seed)
    client, model, inference = client_from_env()
    judge_model = args.judge_model or model
    label = args.system + (
        f"/{args.group}" if args.system == "parallel_consensus" else ""
    )
    LOG.info(
        "%s on %s: %d/%d questions (%s, seed=%d), %d repeat(s), concurrency=%d, %s/%s",
        label,
        args.benchmark,
        len(samples),
        len(pool),
        args.sample,
        args.seed,
        args.repeats,
        args.concurrency,
        inference["provider"],
        model,
    )

    async def one(sample: dict, semaphore: asyncio.Semaphore) -> dict:
        async with semaphore:
            if args.system == "single":
                prediction = await answer_single(client, model, sample)
            else:
                prediction = await answer_consensus(
                    client, model, sample, args.group, args.max_rounds
                )
            if sample["grading"] == "judge":
                verdict = await scoring.grade_judge(
                    client, judge_model, sample, prediction
                )
            else:
                verdict = scoring.grade(sample, prediction)
            return {
                "id": sample["id"],
                "bucket": _bucket(sample),
                "correct": bool(verdict["correct"]),
                "extracted": verdict["extracted"],
                "gold": verdict["gold"],
            }

    async def run_once(rep: int) -> dict:
        semaphore = asyncio.Semaphore(args.concurrency)
        items: list[dict] = []
        tasks = [asyncio.create_task(one(s, semaphore)) for s in samples]
        correct = 0
        desc = label if args.repeats == 1 else f"{label} [{rep + 1}/{args.repeats}]"
        with tqdm(total=len(tasks), desc=desc, unit="q") as bar:
            for future in asyncio.as_completed(tasks):
                item = await future
                items.append(item)
                correct += item["correct"]
                bar.update(1)
                bar.set_postfix(acc=f"{correct / len(items):.1%}")
        summary = _summary(args, model, judge_model, inference, samples, items)
        _report(summary)
        if args.record:
            path = _write_result(summary, items, rep if args.repeats > 1 else None)
            LOG.info("result written → %s", path)
        return summary

    summaries = [await run_once(rep) for rep in range(args.repeats)]
    if args.repeats > 1:
        _report_aggregate(label, summaries)
    elif not args.record:
        LOG.info("not written (pass --record to save this result to a file)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run + score a benchmark; print, and optionally save a JSON result file."
    )
    parser.add_argument(
        "--benchmark", required=True, choices=["math500", "gpqa_diamond", "truthfulqa"]
    )
    parser.add_argument(
        "--system", default="single", choices=["single", "parallel_consensus"]
    )
    parser.add_argument(
        "--group",
        default="A",
        choices=list(GROUPS),
        help="roster for parallel_consensus",
    )
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument(
        "--limit", type=int, default=None, help="evaluate only N questions"
    )
    parser.add_argument(
        "--sample",
        default="stratified",
        choices=["stratified", "head"],
        help="how --limit picks: equal-per-difficulty (default) or first-N",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="sampling seed (pins the question set)"
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="run the eval K times (same questions, fresh generations) for mean±std",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--judge-model", default=None, help="override the TruthfulQA judge model"
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="save this result as JSON under data/results/",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show per-agent DECISION logs"
    )
    parser.add_argument(
        "--notes", default="", help="free-text note stored on a saved result"
    )
    args = parser.parse_args(argv)
    return asyncio.run(evaluate(args))


def _bucket(sample: dict) -> str:
    meta = sample["meta"]
    if sample["grading"] == "math":
        return f"level_{meta.get('level')}"
    if sample["benchmark"] == "gpqa_diamond":
        return str(meta.get("domain") or "unknown")
    return str(meta.get("category") or "unknown")


def _breakdown(items: list[dict]) -> dict[str, float]:
    buckets: dict[str, list[bool]] = {}
    for item in items:
        buckets.setdefault(item["bucket"], []).append(item["correct"])
    return {b: sum(v) / len(v) for b, v in sorted(buckets.items())}


def _summary(
    args,
    model: str,
    judge_model: str,
    inference: dict,
    samples: list[dict],
    items: list[dict],
) -> dict:
    """The run's signature + aggregate metrics — what gets printed and saved."""
    is_consensus = args.system == "parallel_consensus"
    n = len(items)
    return {
        "benchmark": args.benchmark,
        "system": args.system,
        "group": args.group if is_consensus else None,
        "max_rounds": args.max_rounds if is_consensus else None,
        "model": model,
        "inference": inference,
        "judge_model": judge_model if args.benchmark == "truthfulqa" else None,
        "n": n,
        "score": sum(i["correct"] for i in items) / n if n else 0.0,
        "breakdown": _breakdown(items),
        "sample": {
            "scheme": args.sample if args.limit else "all",
            "n": n,
            "seed": args.seed,
            "ids_hash": _ids_hash(samples),
        },
        "code_version": _git_version(),
        "concurrency": args.concurrency,
        "notes": args.notes,
    }


def _ids_hash(samples: list[dict]) -> str:
    """A stable digest of the evaluated question ids — equal ⇒ two runs are paired."""
    joined = "\n".join(sorted(s["id"] for s in samples))
    return hashlib.sha256(joined.encode()).hexdigest()[:12]


def _git_version() -> str:
    """Short git sha, suffixed ``-dirty`` if the tree has uncommitted changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True
        ).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except Exception:
        return "unknown"


def _write_result(summary: dict, items: list[dict], rep: int | None = None) -> Path:
    """Save one immutable run record (signature + per-question items) and return its path.
    A repeat index is appended to the filename so K repeats never collide on the timestamp.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parts = [summary["benchmark"], summary["system"]]
    if summary["group"]:
        parts.append(summary["group"])
    suffix = f"_{stamp}" + (f"_rep{rep}" if rep is not None else "")
    out = RESULTS_DIR / ("_".join(parts) + suffix + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        **summary,
        "items": items,
    }
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _report_aggregate(label: str, summaries: list[dict]) -> None:
    """Print mean±std of the score and each difficulty bucket across the repeats."""
    scores = [s["score"] for s in summaries]
    buckets: dict[str, list[float]] = {}
    for summary in summaries:
        for bucket, value in summary["breakdown"].items():
            buckets.setdefault(bucket, []).append(value)
    mean, sd = statistics.mean(scores), _std(scores)
    print(f"\n{label} — {len(summaries)} repeats: {mean:.1%} ± {sd:.1%} (mean ± std)")
    for bucket in sorted(buckets):
        vals = buckets[bucket]
        print(f"    {bucket:<28} {statistics.mean(vals):.1%} ± {_std(vals):.1%}")


def _std(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _report(summary: dict) -> None:
    head = f"{summary['benchmark']} / {summary['system']}"
    if summary["group"]:
        head += f" / {summary['group']}"
    sig = f"n={summary['n']}, {summary['inference']['provider']}, {summary['code_version']}"
    print(f"\n{head}  →  {summary['score']:.1%}  ({sig})")
    for bucket, value in summary["breakdown"].items():
        print(f"    {bucket:<28} {value:.1%}")


if __name__ == "__main__":
    raise SystemExit(main())
