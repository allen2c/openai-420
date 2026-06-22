"""The `run_python` tool — a deterministic, sandboxed calculator for specialists (PRINCIPLES
Law 2 stays intact: this is program logic, executed by the orchestrator, never by the captain).

Grounding is the only proven lever against the hard ceiling (same-model specialists sharing a
knowledge gap and agreeing on a confidently-wrong number): a real computation injects a fact no
amount of same-model debate can produce. The sandbox is `pydantic-monty` — a Rust reimplementation
of Python, run in-process (fast, no subprocess), with a strict allowlist.

ENVELOPE (pinned by tests/test_tools.py): rich Python builtins + the `math` module only. No other
stdlib (statistics/decimal/itertools/...) and no third-party packages (sympy) are importable, so
the tool description tells the model exactly that. The wrapper NEVER raises — its return value is
fed straight back to the model as a tool result — so every failure (runtime, syntax, timeout) is
returned as a deterministic error string instead.
"""

from __future__ import annotations

DEFAULT_TIMEOUT_SECS = 3.0
MAX_OUTPUT_CHARS = 4096
_TRUNCATION_MARKER = "\n…[truncated]"

RUN_PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Execute Python in a sandbox to CHECK any numeric or derivable claim before you "
            "commit your answer — compute the value, verify an arithmetic/algebra step, count a "
            "combinatorial case. `print(...)` your result (the return value of the final "
            "expression is also reported). Available: Python builtins (len, sum, abs, round, "
            "sorted, pow, divmod, range, comprehensions, etc.) and `import math` (factorial, "
            "comb, gcd, isqrt, sqrt, pi, ...). NOTHING else is importable — no sympy, no "
            "numpy, no other stdlib. Use exact integer arithmetic for fractions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute. Print or return the result.",
                }
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}


def run_python(code: str, *, timeout_secs: float = DEFAULT_TIMEOUT_SECS) -> str:
    """Run ``code`` in the monty sandbox; return its printed output and/or final value as text.

    Never raises: a syntax/runtime error or a timeout comes back as ``"Error: <ExcType>: <msg>"``
    so the orchestrator can hand it straight back to the model. Output is truncated to
    ``MAX_OUTPUT_CHARS`` so a runaway ``print`` can't flood the conversation.
    """
    import pydantic_monty as monty

    collector = monty.CollectString()
    try:
        value = monty.Monty(code).run(
            print_callback=collector,
            limits=monty.ResourceLimits(max_duration_secs=timeout_secs),
        )
    except monty.MontyError as exc:
        return _truncate(f"Error: {exc}")
    except Exception as exc:  # never let the tool crash a specialist's turn
        return _truncate(f"Error: {type(exc).__name__}: {exc}")
    return _truncate(_format_result(str(collector.output), value)) or "(no output)"


def _format_result(printed: str, value: object) -> str:
    """Join captured stdout with the trailing expression value (when the model didn't print)."""
    parts = []
    if printed.strip():
        parts.append(printed.rstrip("\n"))
    if value is not None:
        parts.append(repr(value))
    return "\n".join(parts).strip()


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[: MAX_OUTPUT_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
