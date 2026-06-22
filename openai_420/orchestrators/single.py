"""SingleOrchestrator — one model call, no orchestration (the reference baseline).

This is the control these benchmarks measure against: a single careful-expert completion,
no specialists, no rounds. It implements the same ``run`` contract as the multi-agent
systems so the harness dispatches every system uniformly and the comparison is apples to
apples — the only difference between baseline and framework is the orchestration, not the
plumbing around it.
"""

from __future__ import annotations

import openai

from openai_420.agents import DEFAULT_TOOL_BUDGET, run_with_tool_loop
from openai_420.conversation import Conversation
from openai_420.orchestrators.base import Orchestrator, register
from openai_420.trace import warn_if_truncated

SINGLE_SYSTEM = "You are a careful expert. Answer the user's question."
SINGLE_TOOL_NOTE = (
    "You have tools available (each is described to you separately). Decide for yourself when "
    "calling one would make your answer more reliable — for instance to mechanically check or "
    "derive a step you might otherwise get wrong — and skip them when the question doesn't call "
    "for one. If a tool result conflicts with your draft, work out why before trusting either."
)


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


@register("tool_single")
class ToolSingleOrchestrator(Orchestrator):
    """The single baseline GIVEN the same ``run_python`` tool loop as the verifying specialists.

    It exists for the experiment, not the leaderboard: comparing the tool-grounded framework
    against THIS isolates the framework's contribution with tools held equal, so the honest claim
    is "the tool-grounded framework beats both a tool-equipped single and the no-tool framework,"
    never just "beats the no-tool single" (tools inject capability the control must hold fixed).
    """

    @classmethod
    def from_args(
        cls,
        *,
        client: openai.AsyncOpenAI,
        model: str,
        gen_params: dict,
        tool_budget: int = DEFAULT_TOOL_BUDGET,
        **options,
    ) -> "ToolSingleOrchestrator":
        return cls(
            client=client, model=model, gen_params=gen_params, tool_budget=tool_budget
        )

    def __init__(
        self,
        *,
        client: openai.AsyncOpenAI,
        model: str,
        gen_params: dict | None = None,
        tool_budget: int = DEFAULT_TOOL_BUDGET,
    ) -> None:
        self._client = client
        self._model = model
        self._gen_params = gen_params or {}
        self._tool_budget = tool_budget

    async def run(self, user_query: str) -> str:
        conversation = Conversation(
            system=f"{SINGLE_SYSTEM}\n\n{SINGLE_TOOL_NOTE}", user_query=user_query
        )
        content, _ = await run_with_tool_loop(
            self._client,
            self._model,
            conversation,
            tool_budget=self._tool_budget,
            who="tool_single",
            stage="run",
            **self._gen_params,
        )
        return content
