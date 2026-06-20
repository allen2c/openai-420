# Implementation Principles

These are laws, ordered by importance. Earlier laws outrank later ones: **a lower law
may never be satisfied by violating a higher one.** When two pulls conflict, the lower
number wins. Each law is short on purpose — the simpler it reads, the more load it bears.

Grounded in `grok-420-research.md`. The agent roster (how many specialists, their names and
roles) and a possible opening decomposition are still under design. Laws 8–11 reflect the
debate redesign that took JA→ZH fix rate from 11% to 37% (see `openai-420-debate-findings`
memory): the captain detects/locates rather than judges, and selects the answer verbatim.

---

## Law 1 — The orchestrator owns the truth

The shared reality lives in code, not in any model. Nothing exists until the orchestrator
records it in the scratchpad.

## Law 2 — The orchestrator runs the program, not the language

It owns state, scheduling, and the round loop, but never builds a prompt, calls a model, or
judges content. Every decision that requires reading meaning belongs to an agent.

## Law 3 — Specialists run in parallel, never in sequence

Every specialist in a round is dispatched at once and awaited together. Sequencing them is a
bug, not a simplification.

## Law 4 — Agents share a scratchpad; they never address each other

Collaboration happens by reading the one board the orchestrator owns, not by routing messages
between agents. There is no peer-to-peer channel to break.

## Law 5 — Every agent knows the whole roster

Each agent has a name and a role, and every agent's system prompt lists all participants' names
and roles. Specialists carry real personal names; only the captain is titled by role, and no one
debates strangers.

## Law 6 — Each agent's context is an incremental, cached history

An agent's own turns are `assistant` messages; everyone else's new entries arrive as `user`
messages carrying scratchpad JSON. Each round injects only the delta since that agent last saw
the board — never the whole board — so the prefix stays byte-stable and fully cacheable.

## Law 7 — Only the captain delivers the final answer

Specialists produce material; the captain delivers the answer. The user sees one answer, never
raw agent chatter. The captain *selects* it (Law 10) — it does not write a new one.

## Law 8 — The captain detects consensus and locates disagreement — never correctness

Each round ends with the captain calling `conclude(consensus, direction?)`; the orchestrator
branches on that machine-readable flag and never reads prose to decide. The captain is not the
authority on the answer: it only judges whether the specialists agree and, if not, where —
because spotting disagreement has a far lower error rate than knowing the right answer, and a
captain that asserts correctness can override a correct specialist. Consensus ends the debate;
`max_rounds` is the backstop.

## Law 9 — No consensus must carry a neutral list of disputed points

When the captain reports no consensus, `direction` names the specific points where the
specialists differ, neutrally — never which side is right. The debate never continues blind,
and never on the captain's say-so about the answer.

## Law 10 — The final answer is selected from a specialist, verbatim — never re-generated

On termination the captain picks one specialist's answer by number (majority-biased); the
orchestrator returns that answer's deliverable verbatim. The captain may select but never
rewrite, merge, or re-derive — so it cannot corrupt a correct answer or invent a new one.

## Law 11 — Specialists exchange reasons, not just answers

Each round a specialist outputs its reasoning first, then a marker, then the deliverable. The
board therefore carries reasons teammates can weigh — convergence is by the strength of an
argument, not by counting heads. The user receives only the part after the marker.

## Law 12 — Every scratchpad entry has the same shape

An entry is exactly `{round, author, kind, content}`: `author` is a roster name and `kind` is
`answer` (a specialist) or `direction` (the captain). The board holds only debate turns — never
the user query, the roster, or the final answer.

## Law 13 — Sampling temperature is never set; use the provider default

No model call passes `temperature` (or `top_p`) — every request inherits whatever the serving
backend defaults to. Diversity is engineered through epistemology (different specialist
standards, Law 11), not through a sampling knob, so there is nothing to tune here. Pinning a
value would couple results to a parameter that behaves differently across backends and mask the
model's native behavior; leaving it unset keeps each agent's output native to whatever model
serves it. This holds for specialists, the captain, and any eval/judge call alike.

---

<!-- v1 roster (settled, tunable — config, not law): 3 specialists + 1 captain.
       - Harper   — research / fact-checking / evidence          (placeholder name)
       - Benjamin — logic / math / code / verification           (placeholder name)
       - Lucas    — divergent / contrarian / blind-spot hunting  (placeholder name)
       - Captain  — detects consensus, locates disagreement, selects the answer (role-titled)
     Axes are deliberately complementary (reach out / verify in / push back) to maximize
     the diversity that Mixture-of-Agents shows is load-bearing.

     Deferred (revisit after observing v1, then A/B):
     - an opening captain decomposition phase. v1 ships WITHOUT it: every round is
       uniform, and in round 1 specialists answer the raw user query directly.
-->
