"""The agents that own LLM logic (PRINCIPLES Law 2, 7).

This is the only place that builds a prompt and calls a model. The orchestrator never
does. Each agent holds its own incremental Conversation (Law 6) and a cursor over the
shared board.

Async only: every agent method is a coroutine function and the injected client MUST be an
``openai.AsyncOpenAI``. Synchronous clients are rejected at construction.
"""

from __future__ import annotations

import re

import openai

from openai_420.conclude import CONCLUDE_TOOL, Conclusion, parse_conclude
from openai_420.conversation import Conversation
from openai_420.roster import (
    ANSWER_MARKER,
    AgentSpec,
    captain_system_prompt,
    specialist_system_prompt,
)
from openai_420.scratchpad import Scratchpad
from openai_420.trace import log_decision

_CONCLUDE_ACK = "Recorded."
_SELECT_INSTRUCTION = (
    "The debate is over. Below are the specialists' final answers, numbered. Choose the "
    "single best one — prefer the version the majority of specialists agree on. Do NOT "
    "rewrite, merge, or add anything. Output ONLY the number of your choice."
)
_FORCE_CONCLUDE = {"type": "function", "function": {"name": "conclude"}}
_FALLBACK_DIRECTION = (
    "No clear ruling was produced. Each specialist must give a concrete, complete answer "
    "so consensus can be judged next round."
)


def extract_answer(output: str) -> str:
    """The deliverable after the last answer marker; the whole output if the marker is
    absent. Specialists state their reasoning first, then the marker, then the answer, so
    the board carries reasons teammates can weigh — but the user only gets the answer.
    """
    if ANSWER_MARKER in output:
        return output.rsplit(ANSWER_MARKER, 1)[1].strip()
    return output.strip()


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
        response = await _complete_text(
            self._client, self._model, self._conversation.messages
        )
        message = response.choices[0].message
        content = message.content or ""
        self._conversation.add_own_turn(content)
        self._last_seen = round - 1
        log_decision(
            self.name,
            "respond",
            round=round,
            saw=[e.author for e in delta],
            output=content,
            reasoning=_reasoning(message),
        )
        return content


class Captain:
    """The leader. ``judge`` detects consensus and locates disagreement each round; it does
    NOT decide correctness. ``select`` picks one specialist's answer to return verbatim —
    both coroutines. The captain acts after the round's specialists, so its cursor advances
    to the current round (it sees this round's entries), unlike a specialist.
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
            log_decision(
                self.name,
                "judge",
                round=round,
                fallback=True,
                consensus=False,
                direction=_FALLBACK_DIRECTION,
            )
            return Conclusion(consensus=False, direction=_FALLBACK_DIRECTION)
        self._conversation.add_assistant_message(message.model_dump(exclude_none=True))
        if message.tool_calls:
            self._conversation.add_tool_result(message.tool_calls[0].id, _CONCLUDE_ACK)
        conclusion = _interpret_conclusion(message)
        log_decision(
            self.name,
            "judge",
            round=round,
            saw=[e.author for e in delta],
            consensus=conclusion.consensus,
            direction=conclusion.direction,
            reasoning=_reasoning(message),
            fallback=False,
        )
        return conclusion

    async def select(self, candidates: list[str]) -> int:
        """Choose the best specialist answer by number (0-based) — never rewrite it.

        The captain only selects from existing answers, so it cannot corrupt the text or
        re-derive a wrong one; the prompt tells it to follow the specialists' majority.
        """
        numbered = "\n\n".join(f"[{i + 1}]\n{c}" for i, c in enumerate(candidates))
        self._conversation.add_user_message(f"{_SELECT_INSTRUCTION}\n\n{numbered}")
        response = await _complete_text(
            self._client, self._model, self._conversation.messages
        )
        message = response.choices[0].message
        index = _parse_choice(message.content or "", len(candidates))
        log_decision(
            self.name,
            "select",
            chosen=index + 1,
            raw=message.content or "",
            reasoning=_reasoning(message),
        )
        return index


def _interpret_conclusion(message: object) -> Conclusion:
    """Turn the captain's reply into a Conclusion, tolerating a missing tool call.

    If the model skipped the `conclude` tool (no message, or no tool_calls), default to
    no-consensus with a nudge so the debate continues instead of crashing."""
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return Conclusion(consensus=False, direction=_FALLBACK_DIRECTION)
    return parse_conclude(tool_calls[0].function.arguments)


def _parse_choice(content: str, n: int) -> int:
    """First integer in [1, n] from the captain's reply, as a 0-based index (default 0)."""
    for token in re.findall(r"\d+", content):
        value = int(token)
        if 1 <= value <= n:
            return value - 1
    return 0


async def _complete_text(
    client: openai.AsyncOpenAI, model: str, messages: list, *, attempts: int = 4
):
    """A plain (no-tools) completion, retried on a spurious tool call.

    Some backends (Groq's gpt-oss) sporadically emit a built-in tool call (e.g.
    ``container.exec``) even when the request defines no tools, which the API rejects as
    ``400 tool_use_failed``. Generation is stochastic (no fixed temperature, Law 13), so a
    retry simply dodges it; only after ``attempts`` failures does the error propagate. No
    ``temperature``/``top_p`` is passed — provider default by design (Law 13)."""
    last: openai.BadRequestError | None = None
    for _ in range(attempts):
        try:
            return await client.chat.completions.create(model=model, messages=messages)
        except openai.BadRequestError as exc:
            if "tool_use_failed" not in str(exc):
                raise
            last = exc
    raise last


def _reasoning(message: object) -> str:
    """The model's reasoning text, if the backend exposes one (e.g. gpt-oss)."""
    return (
        getattr(message, "reasoning", None)
        or getattr(message, "reasoning_content", None)
        or ""
    )


def _require_async_client(client: object) -> None:
    if not isinstance(client, openai.AsyncOpenAI):
        raise TypeError(
            "Only async OpenAI clients are supported; pass an openai.AsyncOpenAI."
        )
