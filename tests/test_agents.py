from types import SimpleNamespace

import httpx
import openai
import pytest

from openai_420.agents import (
    _CONCLUDE_NUDGE,
    _FALLBACK_DIRECTION,
    Captain,
    Specialist,
    _interpret_conclusion,
    _parse_choice,
    extract_answer,
)
from openai_420.conclude import Conclusion
from openai_420.roster import ANSWER_MARKER, CAPTAIN, SPECIALISTS
from openai_420.scratchpad import Scratchpad

ROSTER = [*SPECIALISTS, CAPTAIN]


def test_interpret_conclusion_defaults_to_continue_when_the_model_skips_the_tool():
    for message in (
        None,
        SimpleNamespace(tool_calls=None),
        SimpleNamespace(tool_calls=[]),
    ):
        conclusion = _interpret_conclusion(message)
        assert conclusion.consensus is False
        assert conclusion.direction  # a non-empty nudge so the debate can continue


def test_interpret_conclusion_parses_a_real_tool_call():
    tool_call = SimpleNamespace(
        function=SimpleNamespace(arguments='{"consensus": true}')
    )
    message = SimpleNamespace(tool_calls=[tool_call])

    assert _interpret_conclusion(message) == Conclusion(consensus=True, direction=None)


@pytest.mark.asyncio
async def test_specialist_respond_returns_nonempty_text(
    openai_client: openai.AsyncOpenAI, openai_model: str
):
    board = Scratchpad()
    harper = Specialist(
        spec=SPECIALISTS[0],
        roster=ROSTER,
        client=openai_client,
        model=openai_model,
        user_query="Tabs or spaces for indentation? Answer in one sentence.",
    )

    text = await harper.respond(board, round=1)

    assert isinstance(text, str)
    assert text.strip()


@pytest.mark.asyncio
async def test_captain_judge_returns_a_conclusion(
    openai_client: openai.AsyncOpenAI, openai_model: str
):
    board = Scratchpad()
    board.append(
        round=1, author="Harper", kind="answer", content="Spaces, for consistency."
    )
    board.append(
        round=1, author="Benjamin", kind="answer", content="Spaces; tabs misalign."
    )
    board.append(
        round=1, author="Lucas", kind="answer", content="Either; pick one and lint it."
    )
    captain = Captain(
        spec=CAPTAIN,
        roster=ROSTER,
        client=openai_client,
        model=openai_model,
        user_query="Tabs or spaces?",
    )

    conclusion = await captain.judge(board, round=1)

    assert isinstance(conclusion, Conclusion)
    assert isinstance(conclusion.consensus, bool)


def _response(message: object, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=None,
    )


def _prose_response(text: str) -> SimpleNamespace:
    """A captain reply that 'thinks out loud' and emits NO tool call (the Ollama failure)."""
    message = SimpleNamespace(tool_calls=None, content=text, reasoning="")
    message.model_dump = lambda exclude_none=True: {"role": "assistant", "content": text}
    return _response(message)


def _tool_response(arguments: str) -> SimpleNamespace:
    call = SimpleNamespace(
        id="call_1", function=SimpleNamespace(name="conclude", arguments=arguments)
    )
    message = SimpleNamespace(tool_calls=[call], content="", reasoning="")
    message.model_dump = lambda exclude_none=True: {
        "role": "assistant",
        "tool_calls": [{"id": "call_1"}],
    }
    return _response(message)


def _captain() -> Captain:
    return Captain(
        spec=CAPTAIN,
        roster=ROSTER,
        client=openai.AsyncOpenAI(api_key="x"),
        model="m",
        user_query="q",
    )


def _board_with_one_answer() -> Scratchpad:
    board = Scratchpad()
    board.append(round=1, author="Harper", kind="answer", content="42")
    return board


@pytest.mark.asyncio
async def test_judge_nudges_then_succeeds_when_first_reply_skips_the_tool(monkeypatch):
    captain = _captain()
    replies = iter([_prose_response("all agree"), _tool_response('{"consensus": true}')])

    async def fake_create(**kwargs):
        return next(replies)

    monkeypatch.setattr(captain._client.chat.completions, "create", fake_create)

    conclusion = await captain.judge(_board_with_one_answer(), round=1)

    assert conclusion == Conclusion(consensus=True, direction=None)
    messages = captain._conversation.messages
    assert any(
        m.get("role") == "user" and m.get("content") == _CONCLUDE_NUDGE for m in messages
    )


@pytest.mark.asyncio
async def test_judge_falls_back_and_rewinds_when_the_tool_call_never_comes(monkeypatch):
    captain = _captain()

    async def fake_create(**kwargs):
        return _prose_response("still no tool call")

    monkeypatch.setattr(captain._client.chat.completions, "create", fake_create)

    conclusion = await captain.judge(_board_with_one_answer(), round=1)

    assert conclusion == Conclusion(consensus=False, direction=_FALLBACK_DIRECTION)
    messages = captain._conversation.messages
    # the failed nudge exchange was rewound: only system, user query, and the round's delta remain
    assert len(messages) == 3
    assert all(m.get("content") != _CONCLUDE_NUDGE for m in messages)


def _api_error() -> openai.APIError:
    """An Ollama-style transport failure (500 'error parsing tool call' / timeout) — any
    openai.APIError; APITimeoutError is the cheapest to construct."""
    return openai.APITimeoutError(request=httpx.Request("POST", "http://localhost:11434"))


@pytest.mark.asyncio
async def test_judge_degrades_on_api_error_then_succeeds(monkeypatch):
    captain = _captain()
    steps = iter([_api_error(), _tool_response('{"consensus": true}')])

    async def fake_create(**kwargs):
        step = next(steps)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(captain._client.chat.completions, "create", fake_create)

    conclusion = await captain.judge(_board_with_one_answer(), round=1)

    assert conclusion == Conclusion(consensus=True, direction=None)


@pytest.mark.asyncio
async def test_judge_falls_back_and_rewinds_when_api_errors_persist(monkeypatch):
    captain = _captain()

    async def fake_create(**kwargs):
        raise _api_error()

    monkeypatch.setattr(captain._client.chat.completions, "create", fake_create)

    conclusion = await captain.judge(_board_with_one_answer(), round=1)

    assert conclusion == Conclusion(consensus=False, direction=_FALLBACK_DIRECTION)
    assert len(captain._conversation.messages) == 3  # nudge exchange rewound


@pytest.mark.asyncio
async def test_select_degrades_to_anchor_on_api_error(monkeypatch):
    captain = _captain()

    async def fake_create(**kwargs):
        raise _api_error()

    monkeypatch.setattr(captain._client.chat.completions, "create", fake_create)

    index = await captain.select(["answer A", "answer B", "answer C"])

    assert index == 0  # a final-call failure falls back to the anchor, never crashes the question


def test_extract_answer_takes_text_after_the_marker():
    output = f"Here is my reasoning.\nIt is sound.\n{ANSWER_MARKER}\nthe deliverable"
    assert extract_answer(output) == "the deliverable"


def test_extract_answer_falls_back_to_whole_output_without_a_marker():
    assert extract_answer("just the answer, no marker") == "just the answer, no marker"


def test_parse_choice_reads_a_one_based_index_into_a_zero_based_one():
    assert _parse_choice("2", 3) == 1
    assert _parse_choice("I choose [3] because it is clearest.", 3) == 2


def test_parse_choice_defaults_to_first_on_garbage_or_out_of_range():
    assert _parse_choice("no number here", 3) == 0
    assert _parse_choice("5", 3) == 0  # out of [1, 3]


def test_specialist_rejects_a_sync_client():
    with pytest.raises(TypeError):
        Specialist(
            spec=SPECIALISTS[0],
            roster=ROSTER,
            client=openai.OpenAI(api_key="x"),
            model="m",
            user_query="q",
        )
