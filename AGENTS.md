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
  medium); instruct models reject it — leave it unset for them.

Modules: `scratchpad.py` (the board) · `roster.py` (agents + system prompts + `GROUPS`) ·
`conversation.py` (per-agent cached history) · `conclude.py` (captain's control tool) ·
`agents.py` (Specialist/Captain — the only LLM callers, async-only) ·
`orchestrators/parallel_consensus.py` (the v1 loop) · `trace.py` (decision logging).

Orchestrator variants are kept forever and named by mechanism (never a bare `Orchestrator`).

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

The formal harness is `scripts/benchmarks/` — **read its `README.md`**. Three benchmarks
(`math500`, `gpqa_diamond` gated, `truthfulqa`), objective grading where possible
(`math_verify` / MC letter), paired McNemar significance, mean±std over `--repeats`.

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
