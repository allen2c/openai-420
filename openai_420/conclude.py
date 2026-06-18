"""The captain's per-round control signal (PRINCIPLES Law 8, 9, 10).

Each round the captain calls the ``conclude`` tool. The orchestrator branches on the
machine-readable ``consensus`` flag and never reads prose to decide. When there is no
consensus the captain must supply a ``direction`` for the next round; on consensus it is
omitted. The tool never carries the answer — that is a separate, consensus-gated turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CONCLUDE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "conclude",
        "description": (
            "Report whether the specialists have reached consensus. If not, you MUST "
            "give a direction to focus the next round of debate. Do not include the "
            "final answer here."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "consensus": {
                    "type": "boolean",
                    "description": "True if the team has converged and the debate can end.",
                },
                "direction": {
                    "type": "string",
                    "description": "Required when consensus is false: where to focus next round.",
                },
            },
            "required": ["consensus"],
        },
    },
}


def parse_conclude(arguments: str) -> Conclusion:
    data = json.loads(arguments)
    return Conclusion(
        consensus=bool(data["consensus"]),
        direction=data.get("direction"),
    )


@dataclass(frozen=True)
class Conclusion:
    consensus: bool
    direction: str | None
