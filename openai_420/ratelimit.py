"""Client-side rate governing — keep request/token rate under the provider's RPM/TPM so a
sustained burst never exhausts retries mid-run (the limits are pinned + recorded, like the
inference params of Law 13, not left to the SDK's opaque backoff).

Groq's gpt-oss-20b rejects over-budget calls with ``429`` (TPM 250k). The tool orchestrator
multiplies model calls per turn, so at any real concurrency the offered load blows past TPM and
the SDK's retries get exhausted — then one terminal 429 kills the whole 500-question run. The fix
is PROACTIVE: a shared token bucket per limit that paces every call BEFORE it is sent, with an
explicit, observable exponential backoff (honoring ``retry-after``) as the safety net for the
residual bursts.

``ThrottledClient`` wraps an ``openai.AsyncOpenAI`` so call sites are unchanged: it exposes
``chat.completions.create`` with the same signature, estimates the call's token cost, waits for
RPM+TPM capacity, sends with backoff, then reconciles the reservation against actual usage from
``response.usage`` (so reserving the full ``max_completion_tokens`` up front doesn't throttle the
run to a crawl)."""

from __future__ import annotations

import asyncio
import random
import time

import openai

from openai_420.trace import log_decision

DEFAULT_RPM = 1000
DEFAULT_TPM = 250_000
DEFAULT_MAX_RETRIES = 8
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 30.0
_DEFAULT_COMPLETION_EST = 1024  # when max_completion_tokens is unset
_CHARS_PER_TOKEN = 4  # rough; reconciliation against real usage corrects it


def governor_from_env(getenv) -> "RateGovernor":
    """Build a governor from ``OPENAI_RPM`` / ``OPENAI_TPM`` / ``OPENAI_MAX_RETRIES`` /
    ``OPENAI_BACKOFF_BASE`` (``getenv`` is ``os.environ.get``), falling back to Groq-shaped
    defaults. Returned config is recorded in the run fingerprint so a run is reproducible.
    """

    def _num(name, default, cast):
        value = getenv(name)
        return cast(value) if value not in (None, "") else default

    return RateGovernor(
        rpm=_num("OPENAI_RPM", DEFAULT_RPM, int),
        tpm=_num("OPENAI_TPM", DEFAULT_TPM, int),
        max_retries=_num("OPENAI_MAX_RETRIES", DEFAULT_MAX_RETRIES, int),
        backoff_base=_num("OPENAI_BACKOFF_BASE", DEFAULT_BACKOFF_BASE, float),
    )


class RateGovernor:
    """Two shared token buckets (requests/min and tokens/min) plus the backoff policy. One
    instance is shared across every concurrent question so the buckets bound the WHOLE run.
    """

    def __init__(
        self,
        *,
        rpm: int,
        tpm: int,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
    ) -> None:
        self._requests = _TokenBucket(rpm / 60.0, rpm)
        self._tokens = _TokenBucket(tpm / 60.0, tpm)
        self.rpm = rpm
        self.tpm = tpm
        self.max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap

    @property
    def fingerprint(self) -> dict:
        return {
            "rpm": self.rpm,
            "tpm": self.tpm,
            "max_retries": self.max_retries,
            "backoff_base": self._backoff_base,
        }

    async def reserve(self, estimated_tokens: int) -> None:
        """Block until one request slot AND ``estimated_tokens`` of TPM are available."""
        await self._requests.acquire(1)
        await self._tokens.acquire(estimated_tokens)

    async def reconcile(self, estimated_tokens: int, actual_tokens: int) -> None:
        """Correct the TPM reservation once the real usage is known: refund what we over-reserved,
        or charge the overage (the bucket may go negative, so later calls simply wait longer).
        """
        await self._tokens.adjust(estimated_tokens - actual_tokens)

    def backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        """Seconds to wait before retry ``attempt`` (0-based). Honor the server's ``retry-after``;
        otherwise exponential ``base * 2**attempt`` capped, with 50–100% jitter to de-sync peers.
        """
        if retry_after is not None:
            return retry_after
        ceiling = min(self._backoff_cap, self._backoff_base * (2**attempt))
        return ceiling * (0.5 + random.random() * 0.5)


class ThrottledClient:
    """Transparent wrapper around an ``openai.AsyncOpenAI``: exposes ``chat.completions.create``
    with the same signature, governed by a ``RateGovernor``. Drop-in for the real client.
    """

    def __init__(self, client: openai.AsyncOpenAI, governor: RateGovernor) -> None:
        self._client = client
        self._governor = governor
        self.chat = _Chat(self)

    async def _create(self, **kwargs):
        estimate = _estimate_tokens(
            kwargs.get("messages", []), kwargs.get("max_completion_tokens")
        )
        await self._governor.reserve(estimate)
        holder = _Holder()
        try:
            return await self._send(holder, **kwargs)
        finally:
            actual = holder.actual if holder.actual is not None else estimate
            await self._governor.reconcile(estimate, actual)

    async def _send(self, holder: "_Holder", **kwargs):
        last: Exception | None = None
        for attempt in range(self._governor.max_retries + 1):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                holder.actual = _usage_tokens(response)
                return response
            except (openai.RateLimitError, openai.InternalServerError) as exc:
                last = exc
                if attempt == self._governor.max_retries:
                    break
                delay = self._governor.backoff_delay(attempt, _retry_after(exc))
                log_decision(
                    "ratelimit", "backoff", attempt=attempt, delay=round(delay, 2)
                )
                await asyncio.sleep(delay)
        raise last


def _estimate_tokens(messages: list, max_completion_tokens: int | None) -> int:
    prompt_chars = sum(_message_chars(m) for m in messages)
    prompt = prompt_chars // _CHARS_PER_TOKEN + 8 * len(messages)
    completion = max_completion_tokens or _DEFAULT_COMPLETION_EST
    return prompt + completion


def _message_chars(message: dict) -> int:
    total = len(str(message.get("content") or ""))
    for call in message.get("tool_calls") or []:
        function = call.get("function", {}) if isinstance(call, dict) else {}
        total += len(str(function.get("arguments", ""))) + len(
            str(function.get("name", ""))
        )
    return total


def _usage_tokens(response: object) -> int | None:
    usage = getattr(response, "usage", None)
    return getattr(usage, "total_tokens", None) if usage is not None else None


def _retry_after(exc: openai.APIStatusError) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class _TokenBucket:
    """A continuously-refilling token bucket: ``capacity`` tokens, refilled at ``rate`` per
    second. ``acquire`` blocks until ``amount`` is available; ``adjust`` adds (or, with a negative
    delta, removes) tokens for after-the-fact reconciliation. asyncio-safe under one event loop.
    """

    def __init__(self, rate_per_sec: float, capacity: float) -> None:
        self._rate = rate_per_sec
        self._capacity = capacity
        self._available = capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, amount: float) -> None:
        amount = min(
            amount, self._capacity
        )  # never block forever for more than can ever exist
        while True:
            async with self._lock:
                self._refill()
                if self._available >= amount:
                    self._available -= amount
                    return
                wait = (amount - self._available) / self._rate
            await asyncio.sleep(wait)

    async def adjust(self, delta: float) -> None:
        async with self._lock:
            self._refill()
            self._available = min(self._capacity, self._available + delta)

    def _refill(self) -> None:
        now = time.monotonic()
        self._available = min(
            self._capacity, self._available + (now - self._updated) * self._rate
        )
        self._updated = now


class _Holder:
    """Carries the actual token usage out of the retry loop for reconciliation."""

    def __init__(self) -> None:
        self.actual: int | None = None


class _Chat:
    def __init__(self, owner: ThrottledClient) -> None:
        self.completions = _Completions(owner)


class _Completions:
    def __init__(self, owner: ThrottledClient) -> None:
        self._owner = owner

    async def create(self, **kwargs):
        return await self._owner._create(**kwargs)
