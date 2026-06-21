"""Decision-point logging for the orchestration (debug + optimization aid).

Every agent decision (a specialist's response, the captain's judgement, its final answer)
and every orchestrator control step emits one structured ``DECISION`` record. Experiments
attach a handler to the ``openai_420`` logger to capture a full trace per run, so we can see
what each agent saw, reasoned, and produced — and pinpoint which decision is faulty.
"""

import json
import logging

logger = logging.getLogger("openai_420")


def log_decision(agent: str, event: str, **fields) -> None:
    payload = {"agent": agent, "event": event, **fields}
    logger.info("DECISION %s", json.dumps(payload, ensure_ascii=False, default=str))


def warn_if_truncated(response: object, who: str, what: str) -> bool:
    """Log an error when a completion stopped on ``max_completion_tokens`` (``finish_reason
    == "length"``), meaning its output — reasoning and/or answer — was cut off. Returns True
    when truncated, so callers/tests can count it. This is how we prove the pinned token
    budget (Law 13) is large enough for the chosen ``reasoning_effort``."""
    choices = getattr(response, "choices", None) or []
    if not choices or choices[0].finish_reason != "length":
        return False
    usage = getattr(response, "usage", None)
    logger.error(
        "TRUNCATED %s/%s hit max_completion_tokens (finish_reason=length); usage=%s",
        who,
        what,
        usage,
    )
    return True
