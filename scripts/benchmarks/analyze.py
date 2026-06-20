"""Paired McNemar test over two result files — is one system really better than the other?

    python -m scripts.benchmarks.analyze data/results/<single>.json data/results/<consensus>.json

The two runs MUST be paired (same questions) — verified by ``sample.ids_hash``. McNemar looks
only at the questions the two systems answered DIFFERENTLY: ``b`` = baseline right, treatment
wrong (broke); ``c`` = baseline wrong, treatment right (fixed). Concordant questions carry no
signal. The null hypothesis is that fixes and breaks are equally likely; the exact two-sided
binomial p-value tests it (right for the small samples this project runs). A 5-point accuracy
gap means nothing if it's one lucky question — this says whether to believe it.
"""

from __future__ import annotations

import argparse
import json
from math import comb


def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact binomial p-value over the ``b + c`` discordant pairs (1.0 if none)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) * (0.5**n)
    return min(1.0, 2 * tail)


def analyze(baseline_path: str, treatment_path: str) -> dict:
    baseline = json.loads(open(baseline_path, encoding="utf-8").read())
    treatment = json.loads(open(treatment_path, encoding="utf-8").read())

    bh, th = baseline["sample"]["ids_hash"], treatment["sample"]["ids_hash"]
    if bh != th:
        raise SystemExit(
            f"NOT paired — ids_hash differs ({bh} vs {th}). Re-run both with the same "
            "--benchmark --limit --sample --seed so they hit identical questions."
        )

    base = {i["id"]: i["correct"] for i in baseline["items"]}
    treat = {i["id"]: i["correct"] for i in treatment["items"]}
    fixed = sorted(i for i in base if not base[i] and treat[i])
    broke = sorted(i for i in base if base[i] and not treat[i])
    both_right = sum(1 for i in base if base[i] and treat[i])
    both_wrong = sum(1 for i in base if not base[i] and not treat[i])
    p = mcnemar_exact_p(len(broke), len(fixed))
    return {
        "baseline": baseline,
        "treatment": treatment,
        "n": len(base),
        "a_both_right": both_right,
        "b_broke": broke,
        "c_fixed": fixed,
        "d_both_wrong": both_wrong,
        "p_value": p,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paired McNemar test over two result files."
    )
    parser.add_argument("baseline", help="result JSON of the baseline (e.g. single)")
    parser.add_argument(
        "treatment", help="result JSON of the treatment (e.g. parallel_consensus)"
    )
    parser.add_argument(
        "--alpha", type=float, default=0.05, help="significance threshold"
    )
    args = parser.parse_args(argv)
    _report(analyze(args.baseline, args.treatment), args.alpha)
    return 0


def _label(run: dict) -> str:
    tag = run["system"] + (f"/{run['group']}" if run.get("group") else "")
    provider = (run.get("inference") or {}).get("provider", "?")
    return f"{tag}@{provider}"


def _report(result: dict, alpha: float) -> None:
    base, treat = result["baseline"], result["treatment"]
    b, c = len(result["b_broke"]), len(result["c_fixed"])
    print(
        f"\nPaired McNemar — {base['benchmark']}  (n={result['n']}, ids_hash {base['sample']['ids_hash']})"
    )
    print(f"  baseline   {_label(base):<32} {base['score']:.1%}")
    print(f"  treatment  {_label(treat):<32} {treat['score']:.1%}")
    print(f"\n  both right : {result['a_both_right']}")
    print(f"  FIXED (b✗→t✓): {c}  {result['c_fixed']}")
    print(f"  BROKE (b✓→t✗): {b}  {result['b_broke']}")
    print(f"  both wrong : {result['d_both_wrong']}")

    p = result["p_value"]
    verdict = (
        f"SIGNIFICANT (p={p:.4f} < {alpha}): treatment differs from baseline."
        if p < alpha
        else f"not significant (p={p:.4f} ≥ {alpha}): {c} fixed vs {b} broke could be chance."
    )
    print(f"\n  {verdict}")
    if b + c < 10:
        print(
            f"  [!] only {b + c} discordant pairs — underpowered; raise n for a real verdict."
        )


if __name__ == "__main__":
    raise SystemExit(main())
