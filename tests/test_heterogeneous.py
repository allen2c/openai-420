"""Wiring tests for the heterogeneous_consensus orchestrator — construction only, no network."""

from __future__ import annotations

import pytest

from openai_420 import orchestrators
from openai_420.providers import parse_providers

_LOCAL = "http://localhost:11434/v1"
_ROSTER = (
    f"{_LOCAL}?model=nemotron-3-nano:30b&temperature=1.0,"
    f"{_LOCAL}?model=mistral-small3.2&temperature=0.15,"
    f"{_LOCAL}?model=qwen3.6:35b&temperature=1.0&top_p=0.95,"
    f"{_LOCAL}?model=gpt-oss:20b&temperature=1.0&reasoning_effort=medium"
)


def test_registered():
    assert "heterogeneous_consensus" in orchestrators.names()


def test_from_args_requires_providers():
    with pytest.raises(SystemExit):
        orchestrators.get("heterogeneous_consensus").from_args(
            client=object(), model="m", gen_params={}, providers=None
        )


def test_from_args_splits_specialists_and_captain():
    built = orchestrators.get("heterogeneous_consensus").from_args(
        client=object(),
        model="m",
        gen_params={},
        max_rounds=2,
        providers=parse_providers(_ROSTER),
    )
    assert [p.model for p in built._specialist_providers] == [
        "nemotron-3-nano:30b",
        "mistral-small3.2",
        "qwen3.6:35b",
    ]
    assert built._captain_provider.model == "gpt-oss:20b"
    assert built._max_rounds == 2
    # a client was built per provider (4 distinct entries)
    assert len(built._clients) == 4


def test_duplicate_specialist_names_rejected():
    dup = f"{_LOCAL}?model=gpt-oss:20b,{_LOCAL}?model=gpt-oss:20b,{_LOCAL}?model=mistral-small3.2"
    with pytest.raises(ValueError):
        orchestrators.get("heterogeneous_consensus").from_args(
            client=object(), model="m", gen_params={}, providers=parse_providers(dup)
        )
