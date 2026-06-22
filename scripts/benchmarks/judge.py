"""Apply an out-of-band TruthfulQA judge's verdicts onto a deferred (ungraded) result file.

The generation provider (Groq) and the judge are deliberately decoupled (PRINCIPLES Law 13:
record *who* served the tokens): a model must not grade its own truthfulness. ``run.py
--defer-judge`` emits an ungraded result whose items carry ``correct: null`` plus the
``question``/``extracted`` (candidate)/``correct_answers``/``incorrect_answers`` a judge needs.
An independent **Sonnet** workflow reads those items, returns one TRUE/FALSE verdict per id, and
this module patches them back in, recomputes ``score``/``breakdown``, stamps ``judge_model``,
and writes an immutable finalized result next to the original.

    python -m scripts.benchmarks.judge apply <ungraded.json> <verdicts.json> [--judge-model M]

``<verdicts.json>`` maps ``{id: true|false}`` (the Sonnet workflow's output). The finalized file
is what ``analyze.py``/``plot.py`` consume — same schema as an objective run.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"


def load_ungraded(path: str | Path) -> dict:
    """The deferred result record; raises if it was not produced with ``--defer-judge``."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    pending = [i for i in record["items"] if i.get("correct") is None]
    if not pending:
        raise SystemExit(f"{path}: no ungraded items (already judged?).")
    return record


def apply_verdicts(
    record: dict, verdicts: dict[str, bool], judge_model: str = DEFAULT_JUDGE_MODEL
) -> dict:
    """Return a finalized copy of ``record`` with each item's ``correct`` set from ``verdicts``
    (keyed by id), ``score``/``breakdown`` recomputed, and the judge recorded. Every previously
    ungraded item must have a verdict — a missing id is a hard error, not a silent skip.
    """
    items = [dict(i) for i in record["items"]]
    missing = [
        i["id"] for i in items if i["correct"] is None and i["id"] not in verdicts
    ]
    if missing:
        raise SystemExit(
            f"{len(missing)} ungraded items have no verdict, e.g. {missing[:3]}"
        )
    for item in items:
        if item["correct"] is None:
            item["correct"] = bool(verdicts[item["id"]])
    n = len(items)
    finalized = dict(record)
    finalized["items"] = items
    finalized["judge_model"] = judge_model
    finalized["score"] = sum(i["correct"] for i in items) / n if n else 0.0
    finalized["breakdown"] = _breakdown(items)
    finalized["timestamp"] = datetime.now().isoformat(timespec="seconds")
    return finalized


def write_finalized(source: str | Path, finalized: dict) -> Path:
    """Write the finalized record beside the ungraded source (``*_judged.json``) and return it."""
    source = Path(source)
    out = source.with_name(source.stem + "_judged.json")
    out.write_text(
        json.dumps(finalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ap = sub.add_parser("apply", help="patch verdicts onto an ungraded result file")
    ap.add_argument("ungraded", help="deferred result JSON from run.py --defer-judge")
    ap.add_argument(
        "verdicts", help="JSON mapping {id: true|false} from the Sonnet judge"
    )
    ap.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    args = parser.parse_args(argv)

    record = load_ungraded(args.ungraded)
    verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
    finalized = apply_verdicts(record, verdicts, args.judge_model)
    out = write_finalized(args.ungraded, finalized)
    print(f"finalized → {out}  ({finalized['score']:.1%} over n={finalized['n']})")
    return 0


def _breakdown(items: list[dict]) -> dict[str, float]:
    buckets: dict[str, list[bool]] = {}
    for item in items:
        buckets.setdefault(item["bucket"], []).append(item["correct"])
    return {b: sum(v) / len(v) for b, v in sorted(buckets.items())}


if __name__ == "__main__":
    sys.exit(main())
