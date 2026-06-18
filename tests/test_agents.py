from types import SimpleNamespace

import openai
import pytest

from openai_420.agents import (
    Captain,
    Specialist,
    _interpret_conclusion,
    _parse_choice,
    extract_answer,
)
from openai_420.conclude import Conclusion
from openai_420.roster import CAPTAIN, SPECIALISTS
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


def test_extract_answer_takes_text_after_the_marker():
    output = "Here is my reasoning.\nIt is sound.\n---ANSWER---\nthe deliverable"
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
