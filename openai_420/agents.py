"""The agents that own LLM logic (PRINCIPLES Law 2, 7).

This is the only place that builds a prompt and calls a model. The orchestrator never
does. Each agent holds its own incremental Conversation (Law 6) and a cursor over the
shared board.

Async only: every agent method is a coroutine function and the injected client MUST be an
``openai.AsyncOpenAI``. Synchronous clients are rejected at construction.
"""

from __future__ import annotations

import openai

from openai_420.conclude import CONCLUDE_TOOL, Conclusion, parse_conclude
from openai_420.conversation import Conversation
from openai_420.roster import AgentSpec, captain_system_prompt, specialist_system_prompt
from openai_420.scratchpad import Scratchpad

_CONCLUDE_ACK = "Recorded."
_ANSWER_INSTRUCTION = (
    "The debate is complete. Output ONLY the final answer to the user's original "
    "request — the finished deliverable itself, with no preamble or meta-commentary."
)
_FORCE_CONCLUDE = {"type": "function", "function": {"name": "conclude"}}
_FALLBACK_DIRECTION = (
    "No clear ruling was produced. Each specialist must give a concrete, complete answer "
    "so consensus can be judged next round."
)


class Specialist:
    """A debating specialist. ``respond`` is a coroutine — await it once per round."""

    def __init__(
        self,
        *,
        spec: AgentSpec,
        roster: list[AgentSpec],
        client: openai.AsyncOpenAI,
        model: str,
        user_query: str,
    ) -> None:
        _require_async_client(client)
        self.name = spec.name
        self._client = client
        self._model = model
        self._conversation = Conversation(
            system=specialist_system_prompt(spec, roster), user_query=user_query
        )
        self._last_seen = 0

    async def respond(self, board: Scratchpad, *, round: int) -> str:
        delta = board.delta(for_author=self.name, since_round=self._last_seen)
        if delta:
            self._conversation.add_delta(delta)
        response = await self._client.chat.completions.create(
            model=self._model, messages=self._conversation.messages
        )
        content = response.choices[0].message.content or ""
        self._conversation.add_own_turn(content)
        self._last_seen = round - 1
        return content


class Captain:
    """The leader. ``judge`` rules on consensus each round; ``answer`` writes the final
    reply — both coroutines. The captain acts after the round's specialists, so its cursor
    advances to the current round (it sees this round's entries), unlike a specialist.
    """

    def __init__(
        self,
        *,
        spec: AgentSpec,
        roster: list[AgentSpec],
        client: openai.AsyncOpenAI,
        model: str,
        user_query: str,
    ) -> None:
        _require_async_client(client)
        self.name = spec.name
        self._client = client
        self._model = model
        self._conversation = Conversation(
            system=captain_system_prompt(spec, roster), user_query=user_query
        )
        self._last_seen = 0

    async def judge(self, board: Scratchpad, *, round: int) -> Conclusion:
        delta = board.delta(for_author=self.name, since_round=self._last_seen)
        if delta:
            self._conversation.add_delta(delta)
        self._last_seen = round
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=self._conversation.messages,
                tools=[CONCLUDE_TOOL],
                tool_choice=_FORCE_CONCLUDE,
            )
            message = response.choices[0].message
        except openai.BadRequestError:
            # The model answered in prose instead of calling the tool. Don't crash the
            # run — keep debating (the conversation is left clean for a retry next round).
            return Conclusion(consensus=False, direction=_FALLBACK_DIRECTION)
        self._conversation.add_assistant_message(message.model_dump(exclude_none=True))
        if message.tool_calls:
            self._conversation.add_tool_result(message.tool_calls[0].id, _CONCLUDE_ACK)
        return _interpret_conclusion(message)

    async def answer(self) -> str:
        self._conversation.add_user_message(_ANSWER_INSTRUCTION)
        response = await self._client.chat.completions.create(
            model=self._model, messages=self._conversation.messages
        )
        content = response.choices[0].message.content or ""
        self._conversation.add_own_turn(content)
        return content


def _interpret_conclusion(message: object) -> Conclusion:
    """Turn the captain's reply into a Conclusion, tolerating a missing tool call.

    If the model skipped the `conclude` tool (no message, or no tool_calls), default to
    no-consensus with a nudge so the debate continues instead of crashing."""
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return Conclusion(consensus=False, direction=_FALLBACK_DIRECTION)
    return parse_conclude(tool_calls[0].function.arguments)


def _require_async_client(client: object) -> None:
    if not isinstance(client, openai.AsyncOpenAI):
        raise TypeError(
            "Only async OpenAI clients are supported; pass an openai.AsyncOpenAI."
        )
