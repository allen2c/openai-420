# Implementation Principles

These are laws, ordered by importance. Earlier laws outrank later ones: **a lower law
may never be satisfied by violating a higher one.** When two pulls conflict, the lower
number wins. Each law is short on purpose — the simpler it reads, the more load it bears.

Grounded in `grok-420-research.md`. Laws 1–11 are settled. The agent roster (how many
specialists, their names and roles) and a possible opening decomposition are still under design.

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

## Law 7 — Only the captain speaks to the user

Specialists produce material; the captain produces the answer. The user sees one synthesized
response, never raw agent chatter.

## Law 8 — The captain judges consensus every round through a tool call

Each round ends with the captain calling `conclude(consensus, direction?)`; the orchestrator
branches on that machine-readable flag and never reads prose to decide. Consensus ends the
debate; `max_rounds` is the backstop.

## Law 9 — No consensus must carry a direction

When the captain reports no consensus it must supply the direction for the next round; when it
reports consensus, direction is omitted. The debate never continues blind.

## Law 10 — The final answer is a separate turn, gated by consensus

The `conclude` tool never carries the answer. On consensus, its tool result tells the captain
to answer and only then does a follow-up completion produce it; a no-consensus call gets no
follow-up completion — the orchestrator just starts the next round.

## Law 11 — Every scratchpad entry has the same shape

An entry is exactly `{round, author, kind, content}`: `author` is a roster name and `kind` is
`answer` (a specialist) or `direction` (the captain). The board holds only debate turns — never
the user query, the roster, or the final answer.

---

<!-- v1 roster (settled, tunable — config, not law): 3 specialists + 1 captain.
       - Harper   — research / fact-checking / evidence          (placeholder name)
       - Benjamin — logic / math / code / verification           (placeholder name)
       - Lucas    — divergent / contrarian / blind-spot hunting  (placeholder name)
       - Captain  — judges consensus, gives direction, synthesizes (role-titled)
     Axes are deliberately complementary (reach out / verify in / push back) to maximize
     the diversity that Mixture-of-Agents shows is load-bearing.

     Deferred (revisit after observing v1, then A/B):
     - an opening captain decomposition phase. v1 ships WITHOUT it: every round is
       uniform, and in round 1 specialists answer the raw user query directly.
-->
