"""ParallelConsensusOrchestrator — the v1 control loop (PRINCIPLES Law 1, 2, 3, 8).

Each round: dispatch every specialist in parallel (Law 3), record their answers on the
board the orchestrator owns (Law 1), then let the captain judge consensus (Law 8). On
consensus the captain answers (Law 10); otherwise its direction is recorded (Law 9) and
the next round begins. ``max_rounds`` is the backstop.

This is program logic only (Law 2): it schedules and records, but never builds a prompt,
calls a model, or reads prose to decide — it branches on the captain's boolean flag.

Many orchestrator variants will live beside this one and old ones are never deleted, so
the name states its mechanism: parallel specialists + captain-judged consensus.
"""

from __future__ import annotations

import asyncio

import openai

from openai_420.agents import Captain, Specialist, extract_answer
from openai_420.roster import CAPTAIN, SPECIALISTS, AgentSpec
from openai_420.scratchpad import Scratchpad
from openai_420.trace import log_decision

DEFAULT_MAX_ROUNDS = 3


class ParallelConsensusOrchestrator:
    def __init__(
        self,
        *,
        client: openai.AsyncOpenAI,
        model: str,
        specialist_specs: list[AgentSpec] = SPECIALISTS,
        captain_spec: AgentSpec = CAPTAIN,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        gen_params: dict | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._specialist_specs = specialist_specs
        self._captain_spec = captain_spec
        self._max_rounds = max_rounds
        self._gen_params = gen_params or {}

    async def run(self, user_query: str) -> str:
        roster = [*self._specialist_specs, self._captain_spec]
        specialists = [
            Specialist(
                spec=spec,
                roster=roster,
                client=self._client,
                model=self._model,
                user_query=user_query,
                gen_params=self._gen_params,
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
        return answers[await captain.select(list(answers))]
