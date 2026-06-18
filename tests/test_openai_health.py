import openai
import pytest


@pytest.mark.asyncio
async def test_openai_health(openai_client: openai.AsyncOpenAI, openai_model: str):
    response = await openai_client.chat.completions.create(
        model=openai_model,
        messages=[{"role": "user", "content": "Repeat: Hello, world!"}],
    )
    assert response.choices[0].message.content is not None
