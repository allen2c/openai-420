"""Each agent's incremental, cached message history (PRINCIPLES Law 6).

An agent's own turns are ``assistant`` messages; everyone else's new entries arrive as
``user`` messages carrying scratchpad JSON. Only the delta is ever appended — never the
whole board — so the prefix stays byte-stable and fully cacheable.
"""

import json
from dataclasses import asdict

from openai_420.scratchpad import Entry


def render_delta(entries: list[Entry]) -> str:
    return json.dumps([asdict(e) for e in entries], indent=2)


class Conversation:
    def __init__(self, system: str, user_query: str) -> None:
        self._messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_query},
        ]

    @property
    def messages(self) -> list[dict]:
        return list(self._messages)

    def add_own_turn(self, content: str) -> None:
        self._messages.append({"role": "assistant", "content": content})

    def add_user_message(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_delta(self, entries: list[Entry]) -> None:
        self.add_user_message(render_delta(entries))

    def add_assistant_message(self, message: dict) -> None:
        self._messages.append(message)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )
