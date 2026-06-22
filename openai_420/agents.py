"""The agents that own LLM logic (PRINCIPLES Law 2, 7).

This is the only place that builds a prompt and calls a model. The orchestrator never
does. Each agent holds its own incremental Conversation (Law 6) and a cursor over the
shared board.

Async only: every agent method is a coroutine function and the injected client MUST be an
``openai.AsyncOpenAI``. Synchronous clients are rejected at construction.
"""

from __future__ import annotations

import asyncio
import json
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
from openai_420.tools import RUN_PYTHON_TOOL, run_python
from openai_420.trace import log_decision, warn_if_truncated

DEFAULT_TOOL_BUDGET = 3
SPECIALIST_TOOL_NOTE = (
    "You have a `run_python` tool — a sandboxed Python calculator (builtins + `import math` "
    "only; nothing else importable). Before you commit any numeric, algebraic, or combinatorial "
    "answer, USE IT to actually compute or check the step rather than trusting mental "
    "arithmetic: you and your teammates run on the same model and may share the same blind spot, "
    "and a real calculation is the one thing that can break a confident shared mistake. Show the "
    "check in your reasoning above the marker. If the tool result contradicts your draft, trust "
    "the tool and fix your answer."
)
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


async def run_with_tool_loop(
    client: openai.AsyncOpenAI,
    model: str,
    conversation: Conversation,
    *,
    tool_budget: int,
    who: str,
    stage: str,
    **params,
) -> tuple[str, list[dict]]:
    """Drive a bounded ``run_python`` tool-call loop on ``conversation``; return (content, trace).

    The model is offered the tool (``tool_choice="auto"``) and decides whether to compute. Each
    tool call is executed deterministically by the orchestrator (Law 2) and its result appended
    to the conversation, then the model is re-invoked — up to ``tool_budget`` times. If the budget
    is exhausted while the model still wants to compute, one final no-tool completion forces the
    answer. ``trace`` records each {code, result} for the decision log."""
    trace: list[dict] = []
    response = await _complete_tooled(client, model, conversation.messages, **params)
    warn_if_truncated(response, who, stage)
    message = response.choices[0].message
    for _ in range(tool_budget):
        if not message.tool_calls:
            break
        await _apply_tool_calls(message, conversation, trace)
        response = await _complete_tooled(
            client, model, conversation.messages, **params
        )
        warn_if_truncated(response, who, stage)
        message = response.choices[0].message
    else:
        if message.tool_calls:
            await _apply_tool_calls(message, conversation, trace)
            response = await _complete_text(
                client, model, conversation.messages, **params
            )
            warn_if_truncated(response, who, stage)
            message = response.choices[0].message
    return message.content or "", trace


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
        gen_params: dict | None = None,
        tools_note: str = "",
    ) -> None:
        _require_async_client(client)
        self.name = spec.name
        self._client = client
        self._model = model
        self._gen_params = gen_params or {}
        self._conversation = Conversation(
            system=specialist_system_prompt(spec, roster, tools_note),
            user_query=user_query,
        )
        self._last_seen = 0

    async def respond(self, board: Scratchpad, *, round: int) -> str:
        delta = board.delta(for_author=self.name, since_round=self._last_seen)
        if delta:
            self._conversation.add_delta(delta)
        response = await _complete_text(
            self._client, self._model, self._conversation.messages, **self._gen_params
        )
        warn_if_truncated(response, self.name, "respond")
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
        gen_params: dict | None = None,
    ) -> None:
        _require_async_client(client)
        self.name = spec.name
        self._client = client
        self._model = model
        self._gen_params = gen_params or {}
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
                **self._gen_params,
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
        warn_if_truncated(response, self.name, "judge")
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
            self._client, self._model, self._conversation.messages, **self._gen_params
        )
        warn_if_truncated(response, self.name, "select")
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


class VerifyingSpecialist(Specialist):
    """A Specialist that may call ``run_python`` to ground its answer before committing it.

    Identical debate behavior to ``Specialist`` (same prompt + the tool note, same board, same
    reasons-exchange, Law 11) — the only change is the bounded tool-call loop inside ``respond``.
    The tool injects a fact outside the shared same-model knowledge distribution, the one lever
    against confident shared mistakes (the hard ceiling). The captain never sees the tool.
    """

    def __init__(self, *, tool_budget: int = DEFAULT_TOOL_BUDGET, **kwargs) -> None:
        super().__init__(tools_note=SPECIALIST_TOOL_NOTE, **kwargs)
        self._tool_budget = tool_budget

    async def respond(self, board: Scratchpad, *, round: int) -> str:
        delta = board.delta(for_author=self.name, since_round=self._last_seen)
        if delta:
            self._conversation.add_delta(delta)
        content, tool_trace = await run_with_tool_loop(
            self._client,
            self._model,
            self._conversation,
            tool_budget=self._tool_budget,
            who=self.name,
            stage="respond",
            **self._gen_params,
        )
        self._conversation.add_own_turn(content)
        self._last_seen = round - 1
        log_decision(
            self.name,
            "respond",
            round=round,
            saw=[e.author for e in delta],
            output=content,
            tools=tool_trace,
        )
        return content


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


async def _apply_tool_calls(
    message: object, conversation: Conversation, trace: list[dict]
) -> None:
    """Record a tool-calling assistant turn, execute each call, append its result. Mutates the
    conversation and the trace; pure scheduling + deterministic execution (Law 2)."""
    conversation.add_assistant_message(message.model_dump(exclude_none=True))
    for call in message.tool_calls:
        result = await _execute_tool_call(call)
        trace.append({"code": _tool_code(call), "result": result})
        conversation.add_tool_result(call.id, result)


async def _execute_tool_call(call: object) -> str:
    """Run one tool call in the sandbox, off the event loop. Always returns a string (never
    raises): an unknown tool or unparseable arguments come back as a deterministic error the
    model can react to, same as a sandbox error."""
    if call.function.name != "run_python":
        return f"Error: unknown tool {call.function.name!r}"
    try:
        code = json.loads(call.function.arguments)["code"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return f"Error: could not parse run_python arguments: {exc}"
    return await asyncio.to_thread(run_python, code)


def _tool_code(call: object) -> str:
    """The `code` argument of a tool call for the decision log, raw args if unparseable."""
    try:
        return json.loads(call.function.arguments).get("code", "")
    except (json.JSONDecodeError, TypeError):
        return call.function.arguments


async def _complete_tooled(
    client: openai.AsyncOpenAI,
    model: str,
    messages: list,
    *,
    attempts: int = 4,
    **params,
):
    """A completion that OFFERS ``run_python`` (``tool_choice="auto"``), retried on a spurious
    backend tool failure. Unlike ``_complete_text`` (which retries with NO tools to dodge gpt-oss's
    stray ``container.exec``), this keeps our tool defined across retries so a legitimate
    ``run_python`` call is never suppressed — it only re-rolls the stochastic ``400
    tool_use_failed``.

    gpt-oss on Groq/vLLM frequently emits a tool call whose ``arguments`` are not valid JSON
    (e.g. the raw expression instead of ``{"code": ...}``), rejected as ``400 tool_use_failed``;
    it also occasionally returns a different tool-related ``400``. The tool is best-effort, so on
    ANY ``BadRequestError`` from the tool-offered call — ``tool_use_failed`` retried first, any
    other 400 degraded immediately — fall back to a plain no-tool completion instead of raising:
    the specialist still answers (ungrounded this turn) and no backend quirk ever loses a query. A
    genuine config bug still surfaces, because ``_complete_text`` sends the same request minus the
    tool. The degradation is logged so its rate is measurable in a real run."""
    last: openai.BadRequestError | None = None
    for _ in range(attempts):
        try:
            return await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[RUN_PYTHON_TOOL],
                tool_choice="auto",
                **params,
            )
        except openai.BadRequestError as exc:
            last = exc
            if "tool_use_failed" not in str(exc):
                break  # a non-retryable tool 400 — degrade now rather than burn attempts
    log_decision("orchestrator", "tool_degraded", reason=type(last).__name__)
    return await _complete_text(client, model, messages, **params)


async def _complete_text(
    client: openai.AsyncOpenAI,
    model: str,
    messages: list,
    *,
    attempts: int = 4,
    **params,
):
    """A plain (no-tools) completion, retried on a spurious tool call.

    ``params`` are the pinned inference settings (temperature/reasoning_effort/
    max_completion_tokens, Law 13), forwarded to every call. Some backends (Groq's gpt-oss)
    sporadically emit a built-in tool call (e.g. ``container.exec``) even when the request
    defines no tools, which the API rejects as ``400 tool_use_failed``; generation is stochastic,
    so a retry dodges it. Only after ``attempts`` failures does the error propagate."""
    last: openai.BadRequestError | None = None
    for _ in range(attempts):
        try:
            return await client.chat.completions.create(
                model=model, messages=messages, **params
            )
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
