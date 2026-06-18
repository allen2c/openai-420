import os

import openai
import pytest


@pytest.fixture(scope="session")
def openai_client() -> openai.AsyncOpenAI:
    _base_url = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    _api_key = os.getenv("OPENAI_API_KEY")
    if not _api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set.")
    return openai.AsyncOpenAI(base_url=_base_url, api_key=_api_key)


@pytest.fixture(scope="session")
def openai_model() -> str:
    _model = os.getenv("OPENAI_MODEL") or "gpt-oss-20b"
    return _model
