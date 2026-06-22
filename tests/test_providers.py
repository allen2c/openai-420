"""Tests for OPENAI_PROVIDERS parsing (openai_420/providers.py) — pure, no network."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openai_420.providers import (
    Provider,
    mask_secrets,
    parse_providers,
    providers_from_env,
    specialists_and_captain,
)

_LOCAL = "http://localhost:11434/v1"
_ROSTER = (
    f"{_LOCAL}?model=nemotron-3-nano:30b&api_key=dummy&temperature=1.0&top_p=1.0&max_tokens=32768,"
    f"{_LOCAL}?model=mistral-small3.2&api_key=dummy&temperature=0.15&max_tokens=32768,"
    f"{_LOCAL}?model=qwen3.6:35b&api_key=dummy&temperature=1.0&top_p=0.95&max_tokens=32768,"
    f"{_LOCAL}?model=gpt-oss:20b&api_key=dummy&temperature=1.0&reasoning_effort=medium&max_tokens=32768"
)


def test_parses_each_entry_to_a_provider():
    providers = parse_providers(_ROSTER)
    assert [p.model for p in providers] == [
        "nemotron-3-nano:30b",
        "mistral-small3.2",
        "qwen3.6:35b",
        "gpt-oss:20b",
    ]
    assert providers[0].base_url == _LOCAL
    assert providers[0].temperature == 1.0
    assert providers[2].top_p == 0.95


def test_last_entry_defaults_to_captain():
    providers = parse_providers(_ROSTER)
    assert [p.role for p in providers] == [
        "specialist",
        "specialist",
        "specialist",
        "captain",
    ]
    specialists, captain = specialists_and_captain(providers)
    assert captain.model == "gpt-oss:20b"
    assert [s.model for s in specialists] == [
        "nemotron-3-nano:30b",
        "mistral-small3.2",
        "qwen3.6:35b",
    ]


def test_explicit_role_overrides_last_default():
    providers = parse_providers(
        f"{_LOCAL}?model=a&role=captain,{_LOCAL}?model=b,{_LOCAL}?model=c"
    )
    assert [p.role for p in providers] == ["captain", "specialist", "specialist"]
    _, captain = specialists_and_captain(providers)
    assert captain.model == "a"


def test_single_entry_stays_specialist():
    providers = parse_providers(f"{_LOCAL}?model=solo&temperature=0.7")
    assert len(providers) == 1
    assert providers[0].role == "specialist"  # no captain promotion for a lone provider


def test_max_tokens_alias_and_max_completion_tokens_both_work():
    a = parse_providers(f"{_LOCAL}?model=m&max_tokens=8192")[0]
    b = parse_providers(f"{_LOCAL}?model=m&max_completion_tokens=8192")[0]
    assert a.max_completion_tokens == b.max_completion_tokens == 8192


def test_keys_are_case_insensitive_and_dash_underscore_interchangeable():
    p = parse_providers(
        f"{_LOCAL}?model=m&Temperature=0.3&Max-Tokens=4096&Reasoning-Effort=high"
    )[0]
    assert p.temperature == 0.3
    assert p.max_completion_tokens == 4096
    assert p.reasoning_effort == "high"


def test_agent_name_derived_from_model_or_overridden():
    assert Provider(base_url=_LOCAL, model="gpt-oss:20b").agent_name == "gpt-oss"
    assert (
        Provider(base_url=_LOCAL, model="openai/gpt-oss-20b").agent_name
        == "gpt-oss-20b"
    )
    assert Provider(base_url=_LOCAL, model="x", name="Iris").agent_name == "Iris"


def test_gen_params_includes_only_set_inference_keys():
    p = parse_providers(
        f"{_LOCAL}?model=m&temperature=1.0&top_p=0.95&max_tokens=32768&rpm=60"
    )[0]
    assert p.gen_params() == {
        "temperature": 1.0,
        "top_p": 0.95,
        "max_completion_tokens": 32768,
    }
    # role/rpm/tpm/model are NOT inference params
    assert "rpm" not in p.gen_params()


def test_api_key_is_a_secret_and_never_serialized():
    p = parse_providers(f"{_LOCAL}?model=m&api_key=gsk_REALSECRET")[0]
    assert "gsk_REALSECRET" not in repr(p)
    assert "gsk_REALSECRET" not in p.model_dump_json()
    assert p.api_key.get_secret_value() == "gsk_REALSECRET"


def test_mask_secrets_redacts_api_key_in_raw_string():
    masked = mask_secrets(f"{_LOCAL}?api_key=gsk_REALSECRET&model=m")
    assert "gsk_REALSECRET" not in masked
    assert "api_key=***" in masked


def test_unknown_query_key_is_rejected():
    with pytest.raises(ValidationError):
        parse_providers(
            f"{_LOCAL}?model=m&top_k=20"
        )  # top_k not settable via the OpenAI API


def test_malformed_entry_raises():
    with pytest.raises(ValueError):
        parse_providers("not-a-url&model=m")


def test_providers_from_env_returns_none_when_unset():
    assert providers_from_env({"OPENAI_PROVIDERS": ""}.get) is None
    assert providers_from_env({}.get) is None
    assert providers_from_env({"OPENAI_PROVIDERS": _ROSTER}.get) is not None
