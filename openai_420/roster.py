"""The roster: who is in the room (PRINCIPLES Law 5).

Each agent has a name and a role. Every agent's system prompt lists all participants'
names and roles, so no one debates strangers. Specialists carry real personal names;
only the captain is titled by role.
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


def system_prompt(spec: AgentSpec, roster: list[AgentSpec]) -> str:
    participants = "\n".join(f"- {member.name}: {member.role}" for member in roster)
    return (
        f"You are {spec.name}. Your role: {spec.role}.\n\n"
        f"The participants in this debate are:\n{participants}"
    )
