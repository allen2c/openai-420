import openai
import pytest

from openai_420.agents import Captain, Specialist
from openai_420.conclude import Conclusion
from openai_420.roster import CAPTAIN, SPECIALISTS
from openai_420.scratchpad import Scratchpad

ROSTER = [*SPECIALISTS, CAPTAIN]


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


def test_specialist_rejects_a_sync_client():
    with pytest.raises(TypeError):
        Specialist(
            spec=SPECIALISTS[0],
            roster=ROSTER,
            client=openai.OpenAI(api_key="x"),
            model="m",
            user_query="q",
        )
