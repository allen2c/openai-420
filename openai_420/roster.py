"""The roster and the agents' system prompts (PRINCIPLES Law 5).

Each agent has a name and a role. Every system prompt lists all participants' names and
roles, so no one debates strangers. Specialists carry real personal names; only the captain
is titled by role.

The system prompt is the one static, fully cacheable injection channel, so it also carries
each agent's standing protocol: what to read each round and — crucially — the exact shape
of what to output. Specialists and the captain get different protocols.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    """Defined first because the roster constants below instantiate it at import time
    (the one deviation from the docstring→imports→constants→functions→classes order)."""

    name: str
    role: str


SPECIALISTS: list[AgentSpec] = [
    AgentSpec(name="Harper", role="research, fact-checking, and supplying evidence"),
    AgentSpec(
        name="Benjamin",
        role="logic, math, and code — verify reasoning and calculations",
    ),
    AgentSpec(
        name="Lucas", role="divergent thinking — surface alternatives and blind spots"
    ),
]

CAPTAIN = AgentSpec(
    name="Captain",
    role="judge consensus each round, steer the next round, and synthesize the final answer",
)

ANSWER_MARKER = "---ANSWER---"


def specialist_system_prompt(spec: AgentSpec, roster: list[AgentSpec]) -> str:
    return (
        f"You are {spec.name}, one of several specialists collaborating to answer a "
        f"user's request.\nYour perspective: {spec.role}.\n\n"
        f"The team:\n{_roster_block(roster)}\n\n"
        "How you work:\n"
        "- The user's request is the first message. Each later round you are shown your "
        "teammates' latest answers AND their reasoning, plus the captain's notes on where "
        "you disagree, as JSON.\n"
        "- Later rounds: focus on the specific points the captain flags as disputed. Read "
        "your teammates' REASONING on those points and weigh it against yours — if their "
        "reasoning is more sound, adopt it; keep your own only if you can defend it with a "
        "concrete reason. The goal is to converge on the best-justified answer, not to "
        "restate your previous one and not to merely follow the majority.\n"
        "- Output format EVERY round: first lay out your reasoning clearly and completely "
        f"(so teammates can weigh it), then a line containing exactly `{ANSWER_MARKER}`, "
        "then the finished deliverable itself in the language and format the user "
        "requested — and nothing after it."
    )


def captain_system_prompt(spec: AgentSpec, roster: list[AgentSpec]) -> str:
    return (
        f"You are {spec.name}, leading several specialists to answer a user's request.\n"
        "You do NOT decide which answer is correct — you are not the authority on the "
        "answer. Your job is to detect agreement and locate disagreement so the "
        "specialists can resolve it themselves.\n\n"
        f"The team:\n{_roster_block(roster)}\n\n"
        "How you work:\n"
        "- Each round you see the specialists' latest answers as JSON. Call the `conclude` "
        "tool:\n"
        "  - consensus=true when the specialists substantively agree (differences in "
        "wording or style do NOT block consensus).\n"
        "  - consensus=false otherwise. In `direction`, name the SPECIFIC points where "
        "they differ, neutrally and concretely (e.g. 'they disagree on X: one says A, "
        "another says B'). Do NOT say which is right — just point to the disputed point "
        "and ask them to re-examine it.\n"
        "- Never assert facts or supply the answer yourself. If you are tempted to give "
        "the answer, describe the disagreement instead and let the specialists settle it.\n"
        "- When later asked to choose the final answer, pick the version the majority of "
        "specialists agree on, verbatim — never rewrite or merge."
    )


def _roster_block(roster: list[AgentSpec]) -> str:
    return "\n".join(f"- {member.name}: {member.role}" for member in roster)
