"""SingleOrchestrator — one model call, no orchestration (the reference baseline).

This is the control these benchmarks measure against: a single careful-expert completion,
no specialists, no rounds. It implements the same ``run`` contract as the multi-agent
systems so the harness dispatches every system uniformly and the comparison is apples to
apples — the only difference between baseline and framework is the orchestration, not the
plumbing around it.
"""

from __future__ import annotations

import openai

from openai_420.orchestrators.base import Orchestrator, register
from openai_420.trace import warn_if_truncated

SINGLE_SYSTEM = "You are a careful expert. Answer the user's question."


@register("single")
class SingleOrchestrator(Orchestrator):
    def __init__(
        self,
        *,
        client: openai.AsyncOpenAI,
        model: str,
        gen_params: dict | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._gen_params = gen_params or {}

    async def run(self, user_query: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SINGLE_SYSTEM},
                {"role": "user", "content": user_query},
            ],
            **self._gen_params,
        )
        warn_if_truncated(response, "single", "run")
        return response.choices[0].message.content or ""
