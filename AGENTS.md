# AGENTS.md

Guide for agents working in this repo.

## What this is

`openai-420` rebuilds Grok 4.20's inference-time multi-agent debate from scratch over a local
OpenAI-compatible backend (currently **Groq `openai/gpt-oss-20b`**; was Ollama mistral-small3.2 —
the architecture is model-agnostic): specialist agents debate, a captain detects consensus and
selects the answer.
It is an **experimental research repo** — the point is to learn *when and why* multi-agent
debate helps, measured with numbers.

## Architecture — read `docs/PRINCIPLES.md` first

The design is a set of numbered **laws**, ordered by importance (a later law may never violate
an earlier one). The load-bearing ones:

- **The orchestrator owns the truth and runs the program, not the language** — it holds state +
  the round loop, but never builds a prompt, calls a model, or judges content.
- **Specialists run in parallel, share one scratchpad, never address each other.**
- **The captain detects consensus and *locates* disagreement — it never judges correctness**
  (asserting correctness lets a wrong captain override a correct specialist). It **selects** one
  specialist's answer verbatim; it never re-writes one.
- **Specialists exchange reasons, not just answers** — reasoning first, then the `[[ANSWER]]`
  marker, then the deliverable; the user gets only the part after the marker. (The marker is
  `[[ANSWER]]`, not `---ANSWER---`: a leading `---` renders as a markdown rule and gets split.)
- **Inference settings are pinned & recorded** (Law 13): `temperature` is the model publisher's
  officially recommended value (gpt-oss-20b → 1.0; mistral-small3.2 → 0.15), passed to every call
  and logged in the run's fingerprint. Reasoning models also pin `reasoning_effort` (gpt-oss →
  medium); instruct models reject it — leave it unset for them. `max_completion_tokens` → **32768**
  (gpt-oss at medium burns the whole budget reasoning on hard problems and truncates the answer at
  smaller budgets). **Effort must match difficulty**: `low` eliminates truncation and is ~14×
  cheaper but cripples hard sets (AIME single 50%→20%) — keep medium+ for hard math.

Modules: `scratchpad.py` (the board) · `roster.py` (agents + system prompts + `GROUPS`) ·
`conversation.py` (per-agent cached history) · `conclude.py` (captain's control tool) ·
`agents.py` (Specialist/Captain — the only LLM callers, async-only) ·
`orchestrators/` (the systems — see below) · `tools.py` (the sandboxed `run_python`) ·
`ratelimit.py` (client-side RPM/TPM governor — see below) · `trace.py` (decision logging).

### Orchestrators — abstract base + registry

`orchestrators/base.py` defines the contract every system implements: `async run(user_query)
-> str`, returning the final deliverable with reasoning stripped (the `single` baseline lives
here too, as `SingleOrchestrator`). Variants are **kept forever and named by mechanism** (never
a bare `Orchestrator`): `parallel_consensus` (the v1 loop), `single` (the baseline),
`tool_grounded_verification` (v1 loop + specialists that call the `run_python` sandbox to ground
a numeric/derivable answer — the proven lever against same-model false consensus), and
`tool_single` (single + the same tool loop, the control that holds tools equal). The sandboxed
tool lives in `openai_420/tools.py` (`run_python`, pydantic-monty); the bounded tool-call loop is
`agents.run_with_tool_loop`. Tool grounding breaks the no-tool apples-to-apples contract, so the
honest claim is "tool framework beats BOTH a tool-equipped single AND the no-tool framework."

Adding one is "write the class, register it" — no harness branch per system:

1. Subclass `Orchestrator`, implement `run`, decorate with `@register("<mechanism_name>")`.
2. Override `from_args(*, client, model, gen_params, **options)` if you need harness knobs
   (e.g. `group`, `max_rounds`); the default uses only the shared three. Read what you need
   from `options` so the library never depends on the CLI's arg shape.
3. Import the module in `orchestrators/__init__.py` so it registers on package load.

`scripts/benchmarks/run.py` dispatches by name: `--system` choices come from
`orchestrators.names()`, and it builds one stateless instance via `from_args` (reused across
all concurrent questions — `run()` builds fresh agents and a fresh board per query).

## Diversity = epistemology, not persona

Specialists differ by **epistemology** (a neutral, task-agnostic standard of what counts as a
justified answer), not personas — see `docs/epistemology-research.md`. `roster.GROUPS` holds
swappable teams (`roles`, `A`, `B`, `C`); the orchestrator takes the specialist list as a
parameter. The specialist prompt is a **group-chat** style: moderate-length messages that engage
teammates by name, with each agent committing a complete answer every round.

## Conventions

- Within a file: docstring → imports → constants → public functions → public classes → private.
  (`from __future__ import annotations` when a function precedes a class it returns.)
- Agents are **async-only**; the injected client must be `openai.AsyncOpenAI`.
- TDD: write the failing test first for pure logic. LLM-touching code uses the real client from
  `tests/conftest.py`; assert contracts (types/shape), not exact wording.
- `make fmt` (isort/black/ruff over `openai_420 scripts tests`) before committing; keep
  `ruff check` clean. `make test` runs pytest.

## Running the eval (the source of truth for "does it help")

The formal harness is `scripts/benchmarks/` — **read its `README.md`**. Benchmarks
(`math500`, `aime`, `gpqa_diamond` gated, `truthfulqa`), objective grading where possible
(`math_verify` / MC letter), paired McNemar significance, mean±std over `--repeats`.

Token-heavy runs are paced by a client-side **rate governor** (`ratelimit.py`): it keeps offered
load under the provider's RPM/TPM (`OPENAI_RPM`/`OPENAI_TPM`/`OPENAI_MAX_RETRIES`/
`OPENAI_BACKOFF_BASE`) with an explicit, logged backoff, so the tool orchestrator can't exhaust
retries and crash a run on a 429. `--concurrency` no longer bounds the real token rate — the
governor does — so raise it freely. A question that still fails terminally is recorded as a miss,
never crashing the whole run.

`truthfulqa` is judge-graded, and a model must not grade its own truthfulness — so generation and
judging are decoupled. Run it with `--defer-judge` (predictions only, `correct: null`); an
independent **Sonnet** workflow then grades the saved items and `scripts.benchmarks.judge apply`
patches the verdicts in, producing a `*_judged.json` with the same schema as an objective run.

```
python -m scripts.benchmarks.download all
python -m scripts.benchmarks.run --benchmark math500 --system single --limit 100 --seed 7 --record
python -m scripts.benchmarks.run --benchmark math500 --system parallel_consensus --group A --limit 100 --seed 7 --record
python -m scripts.benchmarks.analyze data/results/<single>.json data/results/<consensus>.json
```

Every run records a reproducible **fingerprint** (model, provider, pinned params, sample
`ids_hash`, git sha). Downloaded datasets and per-run results under `data/` are gitignored;
`data/baselines.yaml` (canonical, hand-maintained) is tracked. A run is comparable to another
only at the same fingerprint — never compare across providers or temperatures.

## Where things stand

The architecture demonstrably works in a clean setting (Groq gpt-oss-20b, math500, n=100, K=5):
single 87.4% → parallel_consensus 94.8% (+7.4pp, McNemar p=0.008, non-overlapping). **But it is
conditional**: debate only helps when the base model has *headroom* (errors to fix) AND those
errors are *independent* — not when the base is saturated, nor when the agents share the same
knowledge gap (same-model "shared error" → confident wrong consensus).

Confounds often dwarf the architecture and must be controlled first: provider/serving,
`reasoning_effort`, and **temperature** (mistral on gpqa: temp 1.0 → 0.15 alone moved 3/10 →
7/10). Architecture-v1 has two structural limits left for v2/v3, not fixable by prompt:
(A) no-consensus → forced-select is near-random; (B) MC false-consensus / shared-model error.
Full detail in the `openai-420-eval-harness` and `openai-420-debate-findings` memories.

**v0.0.3 (tool grounding — NEGATIVE result).** `tool_grounded_verification` (specialists may call
`run_python`) does NOT beat `parallel_consensus` on math500 (n=500, seed 7): the headline contrast
is 1 fixed / 5 broke (p=0.22), directionally negative. The tool is redundant with debate here —
debate already fixes the arithmetic-slip false-consensus the tool targeted, and `parallel_consensus`
is near ceiling (96.8%), so the tool only adds risk. It IS a real math lever (helped `single` +1.0;
HURT on conceptual gpqa), consistent with the research's near-ceiling prediction. Next: harder math
(`aime`) where debate alone can't saturate. Variants are kept forever; the negative result stands as
the finding. Detail in `openai-420-v003-orchestrator-candidates` and `openai-420-tool-prompt-design`.
