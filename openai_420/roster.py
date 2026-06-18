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


def specialist_system_prompt(spec: AgentSpec, roster: list[AgentSpec]) -> str:
    return (
        f"You are {spec.name}, one of several specialists collaborating to answer a "
        f"user's request.\nYour perspective: {spec.role}.\n\n"
        f"The team:\n{_roster_block(roster)}\n\n"
        "How you work:\n"
        "- The user's request is the first message. Each later round you are shown your "
        "teammates' latest contributions and the captain's guidance as JSON.\n"
        "- Read them, then output YOUR OWN complete, improved answer to the user's "
        "request — the finished deliverable itself, never commentary, notes, or analysis "
        "about the task.\n"
        "- Use your perspective to make the answer more correct, but always return the "
        "thing the user asked for, in the language and format they requested."
    )


def captain_system_prompt(spec: AgentSpec, roster: list[AgentSpec]) -> str:
    return (
        f"You are {spec.name}, leading several specialists to answer a user's request.\n\n"
        f"The team:\n{_roster_block(roster)}\n\n"
        "How you work:\n"
        "- Each round you see the specialists' latest answers as JSON. Call the `conclude` "
        "tool:\n"
        "  - consensus=true when their answers substantively agree on the same correct "
        "answer (differences in wording or style do NOT block consensus).\n"
        "  - consensus=false otherwise, with a concrete `direction` naming the specific "
        "error or disagreement to resolve next round.\n"
        "- When you are asked to answer, output ONLY the final answer to the user's "
        "original request — the finished deliverable itself, with no preamble or "
        "meta-commentary."
    )


def _roster_block(roster: list[AgentSpec]) -> str:
    return "\n".join(f"- {member.name}: {member.role}" for member in roster)
