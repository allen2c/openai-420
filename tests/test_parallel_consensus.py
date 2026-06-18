import openai
import pytest

from openai_420.orchestrators.parallel_consensus import ParallelConsensusOrchestrator


@pytest.mark.asyncio
async def test_run_returns_a_final_answer(
    openai_client: openai.AsyncOpenAI, openai_model: str
):
    orchestrator = ParallelConsensusOrchestrator(
        client=openai_client, model=openai_model, max_rounds=1
    )

    answer = await orchestrator.run(
        "Tabs or spaces for indentation? Give one recommendation."
    )

    assert isinstance(answer, str)
    assert answer.strip()
