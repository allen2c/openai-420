"""Probe + contract tests for the sandboxed `run_python` tool (openai_420/tools.py).

Two layers:
1. CAPABILITY PINS — assert the exact pydantic-monty behaviors the tool depends on, so an
   upstream change (it is v0.0.x) breaks here loudly instead of silently degrading the tool.
   These also DOCUMENT the sandbox envelope: rich builtins + `math` only; no other stdlib
   (statistics/decimal/itertools/...) and no third-party (sympy) imports.
2. WRAPPER CONTRACT — the tool the orchestrator calls must NEVER raise (its output is fed back
   to the model as a tool result), must return printed output and/or the final expression
   value, and must stringify every failure (runtime/syntax/timeout) deterministically.
"""

from __future__ import annotations

import pytest

from openai_420.tools import RUN_PYTHON_TOOL, run_python

monty = pytest.importorskip("pydantic_monty")


# ---------------------------------------------------------------- capability pins
def _raw(code: str, secs: float = 3.0):
    collector = monty.CollectString()
    value = monty.Monty(code).run(
        print_callback=collector, limits=monty.ResourceLimits(max_duration_secs=secs)
    )
    return value, str(collector.output)


def test_monty_returns_trailing_expression_value():
    value, _ = _raw("x = 6 * 7\nx")
    assert value == 42


def test_monty_captures_print_output():
    _, printed = _raw("print('hello', 6 * 7)")
    assert printed.strip() == "hello 42"


def test_monty_math_module_is_importable():
    _, printed = _raw(
        "import math\nprint(math.comb(10, 3), math.gcd(48, 36), math.isqrt(144))"
    )
    assert printed.split() == ["120", "12", "12"]


def test_monty_rich_builtins_available():
    value, _ = _raw("sorted([3, 1, 2]) + [pow(2, 10), sum(range(5))]")
    assert value == [1, 2, 3, 1024, 10]


def test_monty_runtime_error_is_catchable_with_original_name():
    with pytest.raises(monty.MontyError) as exc:
        _raw("1 / 0")
    assert "ZeroDivisionError" in str(exc.value)


def test_monty_syntax_error_is_catchable():
    with pytest.raises(monty.MontyError):
        _raw("def f(:")


def test_monty_timeout_is_enforced():
    with pytest.raises(monty.MontyError) as exc:
        _raw("while True:\n    pass", secs=0.3)
    assert "TimeoutError" in str(exc.value)


@pytest.mark.parametrize(
    "module", ["sympy", "numpy", "statistics", "decimal", "itertools"]
)
def test_monty_envelope_excludes_other_modules(module):
    """Locks the boundary: of the useful libs, only `math` is importable. If a future monty adds
    these, this fails and we revisit the tool prompt (which tells the model `math` is the only
    import for computation)."""
    with pytest.raises(monty.MontyError) as exc:
        _raw(f"import {module}")
    assert "ModuleNotFoundError" in str(exc.value)


@pytest.mark.parametrize(
    "code",
    [
        "import os\nos.system('echo pwned')",
        "import os\nos.listdir('/')",
        "open('/etc/passwd').read()",
    ],
)
def test_monty_os_is_inert_no_real_filesystem_or_process(code):
    """`import os` succeeds but the module is hollow without an explicitly granted OSAccess —
    no process/filesystem escape. This is the security boundary the tool relies on (we pass
    neither `os=` nor `mount=`), so assert it loudly."""
    with pytest.raises(monty.MontyError):
        _raw(code)


# ---------------------------------------------------------------- wrapper contract
def test_run_python_returns_printed_output():
    assert run_python("print(2 + 2)") == "4"


def test_run_python_returns_trailing_value_when_nothing_printed():
    assert run_python("7 * 8") == "56"


def test_run_python_supports_math():
    assert run_python("import math\nprint(math.factorial(5))") == "120"


def test_run_python_runtime_error_is_stringified_not_raised():
    out = run_python("1 / 0")
    assert "ZeroDivisionError" in out
    assert out.lower().startswith("error")


def test_run_python_syntax_error_is_stringified_not_raised():
    out = run_python("for x in range(:")
    assert "error" in out.lower()


def test_run_python_timeout_is_stringified_not_raised():
    out = run_python("while True:\n    pass", timeout_secs=0.3)
    assert "TimeoutError" in out


@pytest.mark.parametrize(
    "code", ["", "   ", "None", "import sympy", ")(", "undefined_name", "1/0"]
)
def test_run_python_never_raises(code):
    assert isinstance(run_python(code), str)


def test_run_python_truncates_oversized_output():
    out = run_python("print('x' * 100000)")
    assert len(out) <= 4096


def test_run_python_tool_schema_shape():
    assert RUN_PYTHON_TOOL["type"] == "function"
    fn = RUN_PYTHON_TOOL["function"]
    assert fn["name"] == "run_python"
    params = fn["parameters"]
    assert params["type"] == "object"
    assert list(params["properties"]) == ["code"]
    assert params["properties"]["code"]["type"] == "string"
    assert params["required"] == ["code"]
