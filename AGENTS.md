# AGENTS.md

Guide for agents working in this repo.

## What this is

`openai-420` rebuilds Grok 4.20's inference-time multi-agent debate from scratch over a
local OpenAI-compatible (gpt-oss) backend: specialist agents debate, a captain detects
consensus and selects the answer. It is an **experimental research repo** — the point is to
learn *when and why* multi-agent debate helps, measured with numbers.

## Architecture — read `docs/PRINCIPLES.md` first

The design is a set of numbered **laws**, ordered by importance (a later law may never
violate an earlier one). The load-bearing ones:

- **The orchestrator owns the truth and runs the program, not the language** — it holds
  state + the round loop, but never builds a prompt, calls a model, or judges content.
- **Specialists run in parallel, share one scratchpad, never address each other.**
- **The captain detects consensus and *locates* disagreement — it never judges correctness**
  (asserting correctness lets a wrong captain override a correct specialist). It **selects**
  one specialist's answer verbatim; it never re-writes one.
- **Specialists exchange reasons, not just answers** (reasoning, then a `---ANSWER---`
  marker, then the deliverable; the user gets only the part after the marker).

Modules: `scratchpad.py` (the board) · `roster.py` (agents + system prompts + `GROUPS`) ·
`conversation.py` (per-agent cached history) · `conclude.py` (captain's control tool) ·
`agents.py` (Specialist/Captain — the only LLM callers, async-only) ·
`orchestrators/parallel_consensus.py` (the v1 loop) · `trace.py` (decision logging).

Orchestrator variants are kept forever and named by mechanism (never a bare `Orchestrator`).

## Diversity = epistemology, not persona

Specialists differ by **epistemology** (a neutral, task-agnostic standard of what counts as a
justified answer), not personas — see `docs/epistemology-research.md`. `roster.GROUPS` holds
swappable teams (`roles`, `A`, `B`, `C`); the orchestrator takes the specialist list as a
parameter.

## Conventions

- Within a file: docstring → imports → constants → public functions → public classes →
  private. (`from __future__ import annotations` when a function precedes a class it returns.)
- Agents are **async-only**; the injected client must be `openai.AsyncOpenAI`.
- TDD: write the failing test first for pure logic. LLM-touching code uses the real client
  from `tests/conftest.py`; assert contracts (types/shape), not exact wording.
- `make fmt` (isort/black/ruff) before committing. Keep `ruff check` clean.

## Running the eval (the source of truth for "does it help")

Everything under `experiments/` is git-ignored (run artifacts). The dataset
`data/ja_zh_baseline_failures.jsonl` is 103 ORIGINAL synthesized JA passages that gpt-oss-20b
fails to translate single-pass.

**Measurement must be precise & consistent** — trace, final answer, and judging must come
from ONE run (the model is non-deterministic; separate runs cannot be compared and already
produced a false conclusion once). Use:

```
PYTHONPATH=. python experiments/_pipeline_eval.py <N> <group>   # -> eval_<group>.json + shards
```

then judge the shards with a workflow that returns pass/fail + a **divergence** rating
(none/cosmetic/substantive) per case.

## Where things stand

Fix rate on the baseline-failure corpus, consistent eval: roles 17%, A 27%, B 30%, C 27% —
epistemology groups beat the task-adjacent roles, but **all cap ~30%**. The decisive finding:
**substantive round-1 divergence does NOT predict success** — same-model agents share
knowledge gaps, so debate can't converge to a truth none of them holds. Breaking the ceiling
needs **tools/grounding** or **heterogeneous models**, not more composition tuning. Full
detail in the `openai-420-debate-findings` memory.
