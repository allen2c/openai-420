"""HeterogeneousConsensusOrchestrator — parallel consensus across DIFFERENT models (v0.0.4).

Mechanically identical to ``parallel_consensus`` (parallel specialists each round, captain judges
consensus, verbatim select, ``max_rounds`` backstop). The ONE change is the source of diversity:
each specialist runs a DIFFERENT model (from ``OPENAI_PROVIDERS``), so they have genuinely
different knowledge gaps — the only proven lever against the same-model shared-error ceiling that
lens/persona diversity cannot touch.

This first version ISOLATES the new variable: every specialist shares ONE neutral prompt (no
epistemology persona), so the only difference between them is the model. The honest baseline is
the strongest single model in the roster, not gpt-oss alone. Each provider is pinned to its own
publisher-recommended params (carried in the provider URL); the captain runs the provider tagged
``role=captain`` (default: the last entry), chosen for reliable ``conclude`` tool-calling.
"""

from __future__ import annotations

import asyncio

import openai

from openai_420.agents import Captain, Specialist, extract_answer
from openai_420.orchestrators.base import Orchestrator, register
from openai_420.providers import Provider, specialists_and_captain
from openai_420.ratelimit import RateGovernor, ThrottledClient
from openai_420.roster import CAPTAIN, AgentSpec
from openai_420.scratchpad import Scratchpad
from openai_420.trace import log_decision

DEFAULT_MAX_ROUNDS = 3
_NEUTRAL_ROLE = "careful problem-solver — judges by the rigor of the reasoning"
_NEUTRAL_DISPOSITION = (
    "You work the problem yourself with rigor: reason step by step, actively check your own work "
    "for errors, and commit to the answer you can best justify. You weigh teammates' reasoning on "
    "its merits — adopt a better-argued answer, defend yours when it holds — and converge on the "
    "best-argued answer, not the majority one."
)


def build_client(provider: Provider) -> openai.AsyncOpenAI | ThrottledClient:
    """One client for a provider's endpoint. A provider that declares ``rpm``+``tpm`` gets a rate
    governor; otherwise (e.g. local Ollama) the raw client is used directly."""
    raw = openai.AsyncOpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key.get_secret_value(),
        max_retries=0,
    )
    if provider.rpm and provider.tpm:
        return ThrottledClient(raw, RateGovernor(rpm=provider.rpm, tpm=provider.tpm))
    return raw


@register("heterogeneous_consensus")
class HeterogeneousConsensusOrchestrator(Orchestrator):
    @classmethod
    def from_args(
        cls,
        *,
        providers: list[Provider] | None = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        **options,
    ) -> "HeterogeneousConsensusOrchestrator":
        if not providers:
            raise SystemExit(
                "heterogeneous_consensus needs OPENAI_PROVIDERS set (see .env.example)."
            )
        return cls(providers=providers, max_rounds=max_rounds)

    def __init__(
        self, *, providers: list[Provider], max_rounds: int = DEFAULT_MAX_ROUNDS
    ) -> None:
        specialists, captain = specialists_and_captain(providers)
        names = [p.agent_name for p in specialists]
        if len(set(names)) != len(names):
            raise ValueError(
                f"duplicate specialist names {names}; disambiguate with &name= in OPENAI_PROVIDERS"
            )
        self._specialist_providers = specialists
        self._captain_provider = captain
        self._max_rounds = max_rounds
        self._clients = {id(p): build_client(p) for p in providers}

    async def run(self, user_query: str) -> str:
        roster = [
            AgentSpec(
                name=p.agent_name, role=_NEUTRAL_ROLE, disposition=_NEUTRAL_DISPOSITION
            )
            for p in self._specialist_providers
        ] + [CAPTAIN]
        specialists = [
            Specialist(
                spec=spec,
                roster=roster,
                client=self._clients[id(provider)],
                model=provider.model,
                user_query=user_query,
                gen_params=provider.gen_params(),
            )
            for spec, provider in zip(roster, self._specialist_providers)
        ]
        captain = Captain(
            spec=CAPTAIN,
            roster=roster,
            client=self._clients[id(self._captain_provider)],
            model=self._captain_provider.model,
            user_query=user_query,
            gen_params=self._captain_provider.gen_params(),
        )
        board = Scratchpad()

        for current in range(1, self._max_rounds + 1):
            log_decision("orchestrator", "round_start", round=current)
            answers = await asyncio.gather(
                *(s.respond(board, round=current) for s in specialists)
            )
            for specialist, answer in zip(specialists, answers):
                board.append(
                    round=current, author=specialist.name, kind="answer", content=answer
                )

            conclusion = await captain.judge(board, round=current)
            if conclusion.consensus:
                log_decision(
                    "orchestrator", "terminate", reason="consensus", round=current
                )
                return extract_answer(answers[await captain.select(list(answers))])
            board.append(
                round=current,
                author=captain.name,
                kind="direction",
                content=conclusion.direction or "",
            )

        log_decision(
            "orchestrator", "terminate", reason="max_rounds", round=self._max_rounds
        )
        return extract_answer(answers[await captain.select(list(answers))])
