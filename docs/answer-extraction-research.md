# Answer Elicitation & Extraction: Research and Decision

How should the harness make a model state its final answer, and how should we pull that
answer back out for grading? This note records the industry/research grounding behind the
decision, gathered June 2026, plus how it applies to this codebase.

**Bottom line:** let the model **reason in free text** and end with a convention it was
already trained on — `The answer is (X)` for multiple choice, `\boxed{}` for math — then
extract with **tiered regex / symbolic** parsing. Do **not** force JSON, do **not** route the
answer through tool-calling, and do **not** retry the model when extraction fails. Our custom
`[[ANSWER]]` marker is out-of-distribution and poorly followed; the grader's regex is what
actually saves us.

---

## 1. What the major harnesses actually do

No major harness uses an arbitrary custom marker. They prompt for a phrase the model already
emits and extract it with layered regex; math uses `\boxed{}` brace-counting.

### Multiple choice (GPQA / MMLU)

- **EleutherAI lm-evaluation-harness** (GPQA CoT) runs two filters: a `strict-match`
  (`(?<=The answer is )(.*)`) and a `flexible-extract` `multi_choice_regex` that searches for
  `(A)`/`(B)`/`(C)`/`(D)`, takes the **last** match, and falls back through three sub-stages
  (user regex → regex built from the choice text → a colon pattern `:[\s]*(A|B|C|D)` that
  catches "Answer: B"). Failure → `[invalid]` → scored wrong. MMLU default avoids generation
  entirely: log-likelihood over the four letter tokens.
- **HELM** (GPQA CoT) applies four sequential `re.search` calls (`answer is \(?([A-J])\)?`,
  an `answer:` variant, two `correct answer is …` variants), first match wins.
- **OpenAI simple-evals** prompts "end your response with 'Answer: $LETTER$'" and extracts with
  one regex: `(?i)Answer[ \t]*:[ \t]*\$?([A-D])\$?`. No match → scored 0, no retry.

### Math (MATH / AIME / GSM8K)

- `\boxed{}` is the canonical protocol, extracted by **brace-counting** (regex can't handle
  nested braces): find the rightmost `\boxed`, walk forward tracking `{`/`}` depth, return at
  depth 0. Implemented identically in HELM, lm-eval (Minerva), and HF Math-Verify.
- Integer answers (GSM8K/AIME): strict `The answer is (N)` then a flexible last-number fallback
  with a range filter.
- **Equivalence** after extraction is symbolic (SymPy, `simplify(diff) == 0`), not string
  match. HF Math-Verify's multi-config SymPy raised Open-LLM-Leaderboard scores +4.66 pp/model
  by accepting non-standard-but-equivalent LaTeX. simple-evals uses an LLM equality judge only
  as a fallback.

---

## 2. Structured output reliability on small/local models

- **JSON mode / `response_format`.** Naive-prompted 7–9B models (Llama-3.1-8B, Gemma-2-9B,
  Qwen-2.5-7B) produced ~0% jointly-correct-and-valid-JSON while still reasoning at 77–85%
  — they can reason but not format. Grammar enforcement fixes *syntax* (~90–95% at 7B, ~98% at
  30B+) but not *value* correctness (best "perfect response" only ~52.6% across 21 models).
- **Tool/function calling.** Quality tracks fine-tuning, not size (Qwen3-8B-Q4 F1 0.919 >
  Llama-3.3-70B-Q4 0.607). The hardest failure class is *restraint* — knowing when **not** to
  call — which is exactly the Ollama "skip the forced `conclude` call" failure we already had to
  patch.
- **Constrained decoding** (Outlines/Guidance/llama.cpp grammars). Compliance on hard schemas is
  middling (Guidance 41%, llama.cpp 39%, Outlines 3% empirical) and, critically, constraining the
  **whole** output (including the reasoning) suppresses accuracy; CRANE recovered ~10 pp by
  constraining only the final answer field.
- **Plain regex** on narrow fields beats LLM pipelines in accuracy and is ~10⁴× faster — its one
  weakness is cross-model portability, which tiered fallbacks mitigate.

---

## 3. Do format constraints hurt reasoning?

"Let Me Speak Freely?" (EMNLP 2024) measured the accuracy cost of forcing JSON: GSM8K dropped
−26 pp (Llama-3-8B), −27 pp (GPT-3.5), up to −63 pp (Claude-3-Haiku); parse-error rates were
<1%, so the loss is in the *reasoning*, not the parsing. XML is comparable. A 2025
causal-inference rebuttal finds little effect under proper controls and argues it's instruction
wording, and dottxt shows constrained *decoding* with a reasoning-first schema can *help*. The
reconciliation everyone agrees on: **the harm comes from cramming the chain-of-thought into
rigid fields — reason freely, structure the result afterward.** Our local 17–35B models are
squarely in the affected range.

---

## 4. Separate-extractor and retry patterns

- **Separate extractor.** When primary extraction fails, a *second, read-only* pass is the
  legitimate fallback — symbolic (HF Math-Verify), an LLM equality judge (simple-evals MATH), or
  a fine-tuned extractor (xFinder, ICLR 2025: 93.4% vs 74.4% for best-in-class regex). This is
  extraction, **not** re-generation.
- **Retry-on-missing is deliberately avoided** by lm-eval, HELM, BIG-bench, and simple-evals.
  Re-prompting a model to "reformat" changes *what it answers*, not just the format (MCQ format
  swaps move accuracy 19–58 pp), biases compliant vs non-compliant models, and inflates score
  variance (extraction-method choice alone shifts MCQA scores 2.5–8.7 pts). Infrastructure retry
  (rate limits, 5xx, timeouts) is fine; **answer-content** retry is not.

---

## 5. Recommendation for this harness

| Benchmark | Contract (specialist prompt) | Extraction |
|---|---|---|
| GPQA (A–D) | "end with `The answer is (X)`" | tiered regex: `the answer is (X)` → `Answer: X` → last `(X)` → bare letter |
| AIME (int 0–999) | "end with `The answer is N`" | numeric regex + 0–999 range filter, last-int fallback |
| MATH500 (`\boxed{}`) | "put the final answer in `\boxed{}`" | brace-counting; SymPy equality; LLM/Math-Verify fallback only when boxed absent |

Do **not** use JSON or tool-calling for answer content (−26…−63 pp reasoning on this model
tier, plus the restraint-failure class). Do **not** retry for format. Extraction failure scores
wrong, as in every major harness.

---

## 6. Application to openai-420 (as of this writing)

- `scripts/benchmarks/score.py` **already** implements the recommended approach: a 4-stage MC
  regex cascade (`_CHOICE_PATTERNS`, last-match), `\boxed{}` brace-counting (`_extract_boxed`),
  and SymPy equality via `math_verify` (`grade_math`). This is why the heterogeneous gpqa pilot's
  *completed* questions all extracted correctly even when qwen omitted the marker and emitted a
  bare "Answer: B".
- The custom `[[ANSWER]]` marker (`roster.py` `ANSWER_MARKER`, split by `agents.extract_answer`)
  is therefore **redundant with, and occasionally in conflict with, the grader**: it is followed
  inconsistently (qwen ≈ 11/18 in the pilot), and when present it can return a different value
  than the grader's regex would on the raw text. It still serves Law 11 (separating
  reasoning-for-teammates from the deliverable), so removing it is a deliberate cleanup, not a
  bug fix — **lower priority** than the items below.
- The pilot's actual failures were **infrastructure, not format**: 2 of 3 were Ollama returning
  HTTP 500 "error parsing tool call" when the captain's `conclude` `direction` contained LaTeX /
  newlines / unicode, and 1 was a request timeout. Those are robustness fixes in the captain's
  judge path, tracked separately from this extraction work.

---

## Sources

lm-eval-harness ([extraction.py](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/filters/extraction.py),
[GPQA CoT YAML](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/gpqa/cot_zeroshot/_gpqa_cot_zeroshot_yaml)),
HELM ([GPQA metric](https://github.com/stanford-crfm/helm/blob/main/src/helm/benchmark/metrics/gpqa_chain_of_thought_metric.py),
[math scenario](https://github.com/stanford-crfm/helm/blob/main/src/helm/benchmark/scenarios/math_scenario.py)),
OpenAI [simple-evals](https://github.com/openai/simple-evals/blob/main/gpqa_eval.py),
HF [Math-Verify](https://github.com/huggingface/Math-Verify),
xFinder ([arXiv 2405.11874](https://arxiv.org/abs/2405.11874)),
"Let Me Speak Freely?" ([arXiv 2408.02442](https://arxiv.org/abs/2408.02442)),
causal rebuttal ([arXiv 2509.21791](https://arxiv.org/abs/2509.21791)),
CRANE ([arXiv 2502.09061](https://arxiv.org/abs/2502.09061)),
JSONSchemaBench ([arXiv 2501.10868](https://arxiv.org/abs/2501.10868)),
"LLMs Are Biased Towards Output Formats" ([arXiv 2408.08656](https://arxiv.org/abs/2408.08656)),
"Right Answer, Wrong Score" ([arXiv 2503.14996](https://arxiv.org/abs/2503.14996)).
