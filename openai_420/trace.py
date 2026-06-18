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
