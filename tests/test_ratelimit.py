"""Tests for the client-side rate governor (openai_420/ratelimit.py).

Cover the three behaviors the harness depends on: the token bucket PACES (acquiring beyond the
refill rate blocks), the governor RECONCILES a reservation against real usage, and ThrottledClient
is a transparent drop-in that retries 429s with explicit backoff and degrades by raising only
after the budget is spent.
"""

from __future__ import annotations

import time

import httpx
import openai
import pytest

from openai_420.ratelimit import (
    RateGovernor,
    ThrottledClient,
    _estimate_tokens,
    _TokenBucket,
)


# ------------------------------------------------------------------ token bucket
@pytest.mark.asyncio
async def test_bucket_serves_within_capacity_immediately():
    bucket = _TokenBucket(rate_per_sec=1000, capacity=100)
    start = time.monotonic()
    await bucket.acquire(100)
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_bucket_paces_when_drained():
    bucket = _TokenBucket(rate_per_sec=100, capacity=10)  # refills 100/s
    await bucket.acquire(10)  # drain it
    start = time.monotonic()
    await bucket.acquire(10)  # must wait ~0.1s for refill
    assert time.monotonic() - start >= 0.08


@pytest.mark.asyncio
async def test_bucket_adjust_refunds_and_charges():
    bucket = _TokenBucket(rate_per_sec=1, capacity=100)
    await bucket.acquire(100)  # empty
    await bucket.adjust(50)  # refund 50
    start = time.monotonic()
    await bucket.acquire(50)  # available again without waiting
    assert time.monotonic() - start < 0.05


# ------------------------------------------------------------------ governor
@pytest.mark.asyncio
async def test_governor_reconcile_refunds_overreservation():
    gov = RateGovernor(rpm=10_000, tpm=1000, max_retries=0)
    await gov.reserve(900)  # reserve almost all of the 1000 TPM
    await gov.reconcile(900, 100)  # actually used only 100 → 800 refunded
    start = time.monotonic()
    await gov.reserve(800)  # the refunded room is available without a long wait
    assert time.monotonic() - start < 0.1


def test_backoff_honors_retry_after_else_exponential():
    gov = RateGovernor(rpm=1, tpm=1, backoff_base=1.0, backoff_cap=30.0)
    assert gov.backoff_delay(3, retry_after=2.5) == 2.5
    # exponential with 50–100% jitter: attempt 2 → base*4 = 4, jittered into [2, 4]
    delay = gov.backoff_delay(2, retry_after=None)
    assert 2.0 <= delay <= 4.0


def test_backoff_caps():
    gov = RateGovernor(rpm=1, tpm=1, backoff_base=1.0, backoff_cap=5.0)
    assert gov.backoff_delay(20, retry_after=None) <= 5.0


def test_estimate_tokens_counts_prompt_plus_completion():
    messages = [{"role": "user", "content": "x" * 400}]
    # ~100 prompt tokens (400 chars / 4) + 8 per message + completion budget
    assert _estimate_tokens(messages, max_completion_tokens=500) == 100 + 8 + 500


# ------------------------------------------------------------------ scripted fake raw client
class _Usage:
    def __init__(self, total):
        self.total_tokens = total


class _Choice:
    def __init__(self):
        self.message = type("_M", (), {"content": "ok", "tool_calls": None})()
        self.finish_reason = "stop"


class _Response:
    def __init__(self, total_tokens):
        self.choices = [_Choice()]
        self.usage = _Usage(total_tokens)


class _Completions:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeRawClient:
    def __init__(self, script):
        self.chat = type("_Chat", (), {"completions": _Completions(script)})()


def _rate_limit_error(retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    response = httpx.Response(
        429, headers=headers, request=httpx.Request("POST", "http://x")
    )
    return openai.RateLimitError(
        "429 rate_limit_exceeded", response=response, body=None
    )


# ------------------------------------------------------------------ ThrottledClient
@pytest.mark.asyncio
async def test_throttled_client_is_transparent():
    raw = FakeRawClient([_Response(total_tokens=42)])
    gov = RateGovernor(rpm=10_000, tpm=1_000_000, max_retries=2)
    client = ThrottledClient(raw, gov)
    response = await client.chat.completions.create(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        max_completion_tokens=16,
    )
    assert response.choices[0].message.content == "ok"
    assert raw.chat.completions.calls == 1


@pytest.mark.asyncio
async def test_throttled_client_retries_then_succeeds():
    raw = FakeRawClient([_rate_limit_error(), _Response(total_tokens=10)])
    gov = RateGovernor(rpm=10_000, tpm=1_000_000, max_retries=3, backoff_base=0.001)
    client = ThrottledClient(raw, gov)
    response = await client.chat.completions.create(
        model="m", messages=[{"role": "user", "content": "hi"}]
    )
    assert response.usage.total_tokens == 10
    assert raw.chat.completions.calls == 2


@pytest.mark.asyncio
async def test_throttled_client_raises_after_retries_exhausted():
    raw = FakeRawClient([_rate_limit_error() for _ in range(4)])
    gov = RateGovernor(rpm=10_000, tpm=1_000_000, max_retries=3, backoff_base=0.001)
    client = ThrottledClient(raw, gov)
    with pytest.raises(openai.RateLimitError):
        await client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "hi"}]
        )
    assert raw.chat.completions.calls == 4  # initial + 3 retries
