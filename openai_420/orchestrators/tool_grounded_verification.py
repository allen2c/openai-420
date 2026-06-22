"""ToolGroundedVerificationOrchestrator — v1's loop with tool-grounded specialists (Laws 1, 2, 3, 8).

Mechanically identical to ``parallel_consensus``: parallel specialists each round (Law 3),
answers recorded on the board (Law 1), captain judges consensus (Law 8) and selects verbatim
(Law 10), ``max_rounds`` backstop. The ONE change is that specialists are ``VerifyingSpecialist``
— each may call the sandboxed ``run_python`` tool to CHECK a numeric/derivable claim before
committing its answer. That injects a fact outside the shared same-model knowledge distribution,
the only proven lever against confident shared mistakes (the hard ceiling) that no amount of
same-model debate produces.

Law 2 holds: the orchestrator still only schedules and records, branching on the captain's
boolean. The tool runs deterministically inside a specialist's turn (see ``run_with_tool_loop``);
the captain never calls it and never sees tool output as a verdict, so it stays a non-authority.

Name states the mechanism: tool-grounded verification by the specialists.
"""

from __future__ import annotations

import asyncio

import openai

from openai_420.agents import (
    DEFAULT_TOOL_BUDGET,
    Captain,
    VerifyingSpecialist,
    extract_answer,
)
from openai_420.orchestrators.base import Orchestrator, register
from openai_420.roster import CAPTAIN, GROUPS, SPECIALISTS, AgentSpec
from openai_420.scratchpad import Scratchpad
from openai_420.trace import log_decision

DEFAULT_MAX_ROUNDS = 3


@register("tool_grounded_verification")
class ToolGroundedVerificationOrchestrator(Orchestrator):
    @classmethod
    def from_args(
        cls,
        *,
        client: openai.AsyncOpenAI,
        model: str,
        gen_params: dict,
        group: str = "A",
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        tool_budget: int = DEFAULT_TOOL_BUDGET,
        **options,
    ) -> "ToolGroundedVerificationOrchestrator":
        return cls(
            client=client,
            model=model,
            specialist_specs=GROUPS[group],
            max_rounds=max_rounds,
            tool_budget=tool_budget,
            gen_params=gen_params,
        )

    def __init__(
        self,
        *,
        client: openai.AsyncOpenAI,
        model: str,
        specialist_specs: list[AgentSpec] = SPECIALISTS,
        captain_spec: AgentSpec = CAPTAIN,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        tool_budget: int = DEFAULT_TOOL_BUDGET,
        gen_params: dict | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._specialist_specs = specialist_specs
        self._captain_spec = captain_spec
        self._max_rounds = max_rounds
        self._tool_budget = tool_budget
        self._gen_params = gen_params or {}

    async def run(self, user_query: str) -> str:
        roster = [*self._specialist_specs, self._captain_spec]
        specialists = [
            VerifyingSpecialist(
                spec=spec,
                roster=roster,
                client=self._client,
                model=self._model,
                user_query=user_query,
                gen_params=self._gen_params,
                tool_budget=self._tool_budget,
            )
            for spec in self._specialist_specs
        ]
        captain = Captain(
            spec=self._captain_spec,
            roster=roster,
            client=self._client,
            model=self._model,
            user_query=user_query,
            gen_params=self._gen_params,
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
