# Grok 4.20 Multi-Agent: Implementation Research

Research backing the rebuild of Grok 4.20's inference-time multi-agent system over a
local OpenAI-compatible (gpt-oss) backend. Two web-research passes are merged here:
(1) architecture & literature, (2) UI/UX reverse-engineering. Confidence is flagged
throughout; official sources are distinguished from blog/speculation.

---

## TL;DR

- **Grok 4.20** is a real xAI model family (public beta, Feb 2026) with a
  `grok-4.20-multi-agent-*` variant. Its multi-agent behavior runs server-side and
  is opaque to callers — you cannot route between named sub-agents from client code. [1][2]
- **The execution shape is fork-join** *(HIGH confidence)*: a captain decomposes the
  task → N specialists run **in parallel** → an optional cross-check pass → the captain
  synthesizes one answer. It is **not** sequential and **not** peer-to-peer. [1][3][4]
- **Backend parallelism is strongly evidenced; user-visible simultaneous streaming is
  not.** The consumer chat UI shows a single collapsible "Thoughts" panel, not side-by-side
  agent columns. Visible parallel agent panes appear only in *Grok Build* (the coding CLI),
  a separate product surface. [3][5][6]
- **Cost economics are the strongest indirect signal**: multi-agent overhead is ~1.5–2.5×
  a single call, not ~4×. That is only consistent with a **shared KV-cache prefix across
  concurrent inference paths** — true simultaneity on shared infrastructure, not four
  independent model instances. [7]
- The academic foundation is solid: multi-agent debate (Du et al. 2023) [8],
  self-consistency (Wang et al. 2023) [9], and Mixture-of-Agents (2024) [10] all show
  measurable gains from parallel generation + synthesis, largest on verification-heavy
  tasks (olympiad math, expert QA).
- **Unverified / blog-only**: named agents (Harper/Benjamin/Lucas), ~3T MoE parameter
  count, and the "65% hallucination reduction" claim appear only in secondary sources.
  Treat as community characterization, not fact. [11][12]

---

## 1. What "Grok 4.20" Actually Is

`grok-4.20-multi-agent-*` is accessed via the **Responses API**
(`https://api.x.ai/v1/responses`), not Chat Completions — a hard constraint for the
hosted product [1]. Official docs describe a **leader-worker pattern**:

1. A **leader/captain agent** decomposes the task, assigns sub-tasks, and resolves conflicts.
2. **Worker sub-agents** (4 or 16, selected by the caller) execute in parallel using
   server-side tools (`web_search`, `x_search`, `code_execution`, `collections_search`).
3. The leader synthesizes sub-agent findings into a single final response.

The caller receives only the leader's tool calls and final text. Sub-agent reasoning is
encrypted and hidden by default; `use_encrypted_content=True` (xAI SDK only) restores it
across turns for Zero-Data-Retention continuity [1][2]. Multi-turn continuity uses
`previous_response_id`, not standard conversation history.

**Agent-count control:**

| Mode | xAI SDK | OpenAI-compatible mapping |
|------|---------|---------------------------|
| Focused (4 agents) | `agent_count=4` | `reasoning.effort = "low"`/`"medium"` |
| Deep (16 agents) | `agent_count=16` | `reasoning.effort = "high"`/`"xhigh"` |

**Performance evidence** — the single→Heavy delta isolates the value of parallel compute [13][14]:

| Benchmark | Grok 4 (single, tools) | Grok 4 Heavy (multi-agent) | Δ |
|-----------|------------------------|----------------------------|---|
| HLE (with tools) | 38.6% | 44.4% | +5.8 pp |
| AIME 2025 | 91.7% | 100.0% | +8.3 pp |
| HMMT25 | 90.0% | 96.7% | +6.7 pp |
| GPQA | 87.5% | 88.9% | +1.4 pp |
| LiveCodeBench | 79.0% | 79.4% | +0.4 pp |

Gains are largest on verification-heavy tasks and near-zero where the single model already
nears ceiling — exactly what the debate literature predicts [8][10].

**Agent counts across products (fact, consolidated):**

| Surface | Worker agents | Source level |
|---------|---------------|--------------|
| Grok 4 Heavy / 4.20 (text multi-agent) | **4 or 16**, caller-selected via effort tier | official docs ★★★ [1] |
| Consumer UI, observed | **4** ("4 spawned agents" label, possibly presentational) | hands-on ★★ [3] |
| Grok Build (coding CLI) | **up to 8**, each in its own Git worktree | hands-on ★★☆ [17][18] |

Caveats: 4/16 are *discrete* tiers, not a count that grows dynamically with query difficulty;
the leader/captain is counted separately; whether the consumer product runs 4 or 16 is not
officially stated. **This project deliberately starts at 3 specialists** (Du et al.'s debate
sweet spot [8]) — chosen to *see the mechanism*, not to match Grok's benchmark-pushing 4/16.
Scaling up later is pure parameter tuning.

---

## 2. UI/UX Evidence (Reverse-Engineering the Design)

The interface is an architecture leak: what it shows constrains what the backend can be.

### What users literally see

**grok.com chat (Expert / Heavy modes):**
- A mode selector — "Expert" (single-agent) vs "Heavy" (multi-agent). **No agent tabs or
  columns appear at any point.** [3][5]
- A single collapsible **"Thoughts"** panel during inference (like DeepSeek R1's visible CoT).
  This is the *only* in-progress affordance. [15]
- The final message is **one synthesized block** with **no per-agent attribution**
  ("Harper found X" is never shown in the answer). [4]
- A "4 spawned agents" label that interconnects.ai flags as possibly presentational
  "UX theater" rather than a live count. [3]
- High, visible latency: ~31 s for simple arithmetic, up to ~157 s for hard math — the
  most perceptible differentiator. [16]

**Grok Build (coding CLI + web dashboard — a *different* product surface):**
- A structured execution plan listing every file to be touched, with per-step approval. [17]
- Up to 8 agents in parallel, each in its **own Git worktree on a separate branch**;
  the user reviews a reconciled merged diff. [17][18]
- "Arena Mode" (beta) shows all 8 agent outputs side-by-side with scoring. [18][19]

### Parallelism: the verdict

**Backend parallelism — HIGH confidence. User-visible simultaneous streams — LOW confidence.**

Convergent evidence for true parallel backend execution:
1. Official docs: "multiple agents may run in parallel and each can independently invoke
   tools." [1]
2. Multiple hands-on accounts describe the same fork-join shape with no agent waiting on
   another. [4][6]
3. **Cost economics**: ~1.5–2.5× overhead, not ~4× — only consistent with shared KV-cache
   prefix across concurrent paths. [7]
4. Grok Build's per-agent **Git worktrees** are a filesystem isolation mechanism that only
   makes sense for simultaneous writes. [17][18]

What is *not* evidenced: side-by-side simultaneous agent streams in the grok.com chat UI.
Claims of a "live thinking interface" appear to conflate the standard Thoughts panel with a
purpose-built multi-agent view; no reviewer screenshot corroborates it. [6]

### What the UX rules in / out

| Option | UX evidence | Verdict |
|--------|-------------|---------|
| Parallel specialists → captain synthesis | Supported by all major sources [1][4][6][7] | **IN** |
| Shared context (shared KV cache / scratchpad) | Cost economics + shared-weights imply shared prefix [7] | **IN** |
| Pure sequential | Contradicted by docs, cost, hands-on accounts | **OUT** |
| Peer-to-peer agent↔agent chatroom | Never surfaced in any UI; debate is a server-side pass [4] | **OUT** |
| Best-of-N identical copies | Named roles imply differentiated prompts, not clones | Disfavored |
| Dynamic spawning scaled to query | "Dynamically spawns" + discrete effort tiers [1] | **IN** (discrete tiers) |
| Separate judge/referee layer | Arena Mode implies a scoring referee [18][19] | **IN** (optional) |

---

## 3. Inter-Agent Communication Patterns

The "agents talk via tool calls" idiom uses the LLM's tool-call mechanism as a **routing
primitive**: the model emits a structured call whose target is another agent, and the
framework activates that agent instead of calling an external API. The mainstream
implementations:

**OpenAI Agents SDK — Handoffs** [20]: control *transfers* to the target agent (surfaced as
`transfer_to_<agent>`), which inherits the conversation history via `input_filter`. Only one
agent is active at a time → no parallelism. Good for triage/routing, poor for debate.

**OpenAI Agents SDK — Agent-as-tool** [21]: a sub-agent runs to completion and returns its
output **as a tool result** to the *caller* that invoked it; the orchestrator stays in control.
This is request/response (the caller receives, because the caller asked) — not a third party
pushing a message. Maps cleanly to "captain consults specialists."

**AutoGen Swarm** [22]: a shared message log all agents read. Closest to a "chatroom," but
context grows fastest and `parallel_tool_calls` **must** be disabled or routing is undefined.

**Receiving is not symmetric with sending.** A tool result must match a `tool_call_id` the
*recipient* produced. An agent that didn't make a call has no slot to attach an incoming
message to — so any "inbox" pattern must inject it as a fresh turn, which is exactly the
asymmetry that makes peer-to-peer inboxes fragile. The mainstream frameworks avoid this by
collapsing send+receive into one tool call's round-trip, or by sharing one log.

> **Design consequence for this project:** peer-to-peer messaging is rejected (unstable).
> The chosen substitute is a **shared scratchpad** read by all specialists — debate without
> message routing. See §5.

---

## 4. Debate & Synthesis Techniques (Literature)

**Multi-Agent Debate — Du et al. 2023 / ICML 2024** [8]. N agents answer independently;
responses are concatenated and fed back for R rounds; final answer aggregated. 3 agents × 2
rounds: Arithmetic 67→81.8%, GSM8K 77→85%, MMLU 63.9→71.1%. Plateaus at ~4 rounds;
**summarizing** prior responses beats raw concatenation.

**Self-Consistency — Wang et al. 2023** [9]. Sample N independent chains from one model,
majority-vote. No inter-agent comms. PaLM-540B GSM8K 56.5→74.4%. The tractable lower bound:
diversity + voting, zero routing.

**Mixture-of-Agents — TogetherAI 2024** [10]. **Proposers** (diverse parallel generation) +
**aggregators** (synthesis) in layers. 6 heterogeneous proposers beat 6 identical copies by
4.6 pp — **diversity is mechanically load-bearing**, not cosmetic. Maps directly to
specialists/captain. Caveat: time-to-first-token = full multi-layer depth.

**LLM-as-Judge — Zheng et al. 2023** [23]. GPT-4 agrees with humans ~85%. But position bias
(even GPT-4 ~35% biased) and verbosity bias corrupt judgment — relevant if the captain
evaluates specialists to decide on another round. Mitigate by shuffling order and
reference-guided prompts.

---

## 5. Implementation Guidance for This Project

Locked decisions: **(a) specialists run in parallel** — sequential is rejected;
**(b) no peer-to-peer agent messaging** — too unstable. The remaining design is parallel
independent specialists converging at a captain synthesis, with a **shared scratchpad** for
the optional cross-check.

### The four-phase fork-join shape

1. **Decompose** (sequential, 1 short captain call): captain turns the user query into
   per-specialist subtasks.
2. **Specialists** (parallel, load-bearing): all N specialists run simultaneously as
   concurrent async requests against the local gpt-oss endpoint.
3. **Cross-check** (parallel, optional, 1 round): each specialist reads the *shared
   scratchpad* of everyone's Phase-2 output and flags disagreements. No agent addresses
   another — they all read one board.
4. **Synthesize** (sequential): captain receives all outputs + conflict flags and writes the
   single final answer, noting unresolved uncertainties.

### Shared scratchpad, not message passing

Cost economics and the encrypted-sub-agent design point to a **shared context object**, not
independent histories [1][7]. In practice: maintain one in-memory scratchpad (problem
decomposition + all specialist outputs, labeled by role) and **prepend it** to each agent's
Phase-3/4 call. This is "debate" with zero routing infrastructure — the orchestrator owns the
one true state, every agent reads from it, none writes to another.

### Concrete backend notes

- Point the OpenAI SDK at the local server; most gpt-oss servers support **Chat Completions
  only**, not the Responses API. Use accumulated message lists for continuity.
- Fire Phase 2 with `asyncio.gather` over per-specialist requests.
- Give each specialist a **meaningfully different system prompt** (role + perspective) —
  diversity drives synthesis quality [10].

### Gotchas

1. **Disable parallel tool calls** on routing-style agents or behavior is undefined [22].
2. **Context growth** is the main cost: summarize specialist outputs before appending [8].
3. **Captain position/verbosity bias** [23]: shuffle specialist order before synthesis.
4. **gpt-oss/vLLM** sometimes leave tool JSON in `content` instead of `tool_calls` — parse
   defensively.
5. **Token/latency multiply** with agent count: 4 specialists × a couple of rounds ≈ ~10–15
   model calls per query.

### Convergence detection (preview — under active design)

A structured captain output (`answer`, `confidence`, `requires_another_round`) lets the loop
stop on `requires_another_round == false`, `confidence > threshold`, or `max_rounds`. Exact
termination conditions are the next open design question (see §7).

---

## 6. Open Questions / Unverified

- **Debate round count**: "multiple rounds" is claimed but the UI only shows latency; one
  cross-check round is a reasonable starting assumption. [12]
- **Arbitration logic**: how the captain resolves genuine contradictions is "not publicly
  documented." Weighted vote vs judge-LLM vs captain discretion is an open choice. [6]
- **Shared context data structure**: appended history vs structured JSON vs dedicated object
  is not observable from the UI; `use_encrypted_content` suggests a blob passed between turns. [1]
- **Named agents / 3T MoE / "65% hallucination reduction"**: blog-only, unconfirmed. [11][12]
- **Per-specialist tool access**: whether each specialist sees all tools or only
  role-appropriate ones is inferred, not observed. [1]
- **"4 spawned agents" label accuracy**: flagged as possibly presentational; don't treat as
  ground truth. [3]

---

## Sources

| # | Title | URL | Credibility |
|---|-------|-----|-------------|
| [1] | Multi-Agent Capability — xAI Developer Docs | https://docs.x.ai/developers/model-capabilities/text/multi-agent | official |
| [2] | Advanced Usage (encrypted content, previous_response_id) — xAI Docs | https://docs.x.ai/developers/tools/advanced-usage | official |
| [3] | Grok 4: an o3 look-alike in search — interconnects.ai | https://www.interconnects.ai/p/grok-4-an-o3-look-alike-in-search | hands-on-review |
| [4] | Grok 4.20 Multi-Agent AI Debate — aimaker.substack | https://aimaker.substack.com/p/grok-4-20-multi-agent-ai-debate-llm-council | hands-on-review |
| [5] | Grok 4.20 Multi-Agent Beta 0309 — xAI Docs | https://docs.x.ai/developers/models/grok-4.20-multi-agent-beta-0309 | official |
| [6] | Grok 4.20 Multi-Agent System guide — verdent.ai | https://www.verdent.ai/guides/grok-4-20-multi-agent-system | hands-on-review |
| [7] | Grok 4.20 Review 2026 — aimlapi.com | https://aimlapi.com/blog/grok-4-20-review-2026-everything-you-need-to-know | hands-on-review |
| [8] | Improving Factuality and Reasoning through Multiagent Debate (Du et al., ICML 2024) | https://arxiv.org/abs/2305.14325 | peer-reviewed |
| [9] | Self-Consistency Improves CoT Reasoning (Wang et al., ICLR 2023) | https://arxiv.org/abs/2203.11171 | peer-reviewed |
| [10] | Mixture-of-Agents Enhances LLM Capabilities (arXiv:2406.04692) | https://arxiv.org/html/2406.04692v1 | peer-reviewed preprint |
| [11] | How the xAI Grok 4.20 Agents Work — NextBigFuture | https://www.nextbigfuture.com/2026/02/how-the-xai-grok-4-20-agents-work.html | blog (unverified) |
| [12] | Grok 4.20 Beta 4-Agents Guide — apiyi.com | https://help.apiyi.com/en/grok-4-20-beta-4-agents-guide-en.html | blog (unverified) |
| [13] | Elon Musk's New Grok 4 Takes on Humanity's Last Exam — Scientific American | https://www.scientificamerican.com/article/elon-musks-new-grok-4-takes-on-humanitys-last-exam-as-the-ai-race-heats-up/ | reputable-press |
| [14] | Grok 4: Tests, Features, Benchmarks — DataCamp | https://www.datacamp.com/blog/grok-4 | reputable-press |
| [15] | Grok features — suprmind.ai | https://suprmind.ai/hub/grok/grok-features/ | hands-on-review |
| [16] | Grok 4 benchmarks/latency — DataCamp | https://www.datacamp.com/blog/grok-4 | reputable-press |
| [17] | Grok Build xAI CLI AI Agents 2026 — buildfastwithai | https://www.buildfastwithai.com/blogs/grok-build-xai-cli-ai-agents-2026 | hands-on-review |
| [18] | Grok Build Arena Mode — sdd.sh | https://sdd.sh/2026/05/grok-build-xai-coding-agent-arena-mode/ | hands-on-review |
| [19] | xAI tests parallel agents and Arena Mode — testingcatalog | https://www.testingcatalog.com/xai-tests-parralel-agents-and-arena-mode-for-grok-build/ | hands-on-review |
| [20] | Handoffs — OpenAI Agents SDK | https://openai.github.io/openai-agents-python/handoffs/ | official |
| [21] | Tools (Agent.as_tool) — OpenAI Agents SDK | https://openai.github.io/openai-agents-python/tools/ | official |
| [22] | AutoGen Swarm Pattern — Microsoft AutoGen | https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/swarm.html | official |
| [23] | Judging LLM-as-a-Judge with MT-Bench (Zheng et al., NeurIPS 2023) | https://arxiv.org/abs/2306.05685 | peer-reviewed |
| [24] | Inside Grok 4.20: four agents on one backbone — Medium | https://engineeratheart.medium.com/inside-grok-4-20-how-four-agents-on-one-backbone-beat-separate-models-acefa425cb52 | blog |
| [25] | Grok 4 Heavy Review — binaryverseai | https://binaryverseai.com/grok-4-heavy-review/ | blog (speculative) |
