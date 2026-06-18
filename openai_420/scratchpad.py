"""The shared scratchpad: the one board the orchestrator owns (PRINCIPLES Law 1, 4, 11).

An append-only log of debate entries. Every entry has the same shape
``{round, author, kind, content}`` (Law 11). The orchestrator owns it; agents never
mutate it directly — they return text and the orchestrator records it here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    round: int
    author: str
    kind: str  # "answer" (a specialist) or "direction" (the captain)
    content: str


class Scratchpad:
    def __init__(self) -> None:
        self._entries: list[Entry] = []

    @property
    def entries(self) -> list[Entry]:
        return list(self._entries)

    def append(self, *, round: int, author: str, kind: str, content: str) -> Entry:
        entry = Entry(round=round, author=author, kind=kind, content=content)
        self._entries.append(entry)
        return entry

    def delta(self, *, for_author: str, since_round: int) -> list[Entry]:
        """Entries this agent has not yet seen: authored by others, after ``since_round``.

        This is what the orchestrator injects as the agent's next ``user`` turn (Law 6).
        """
        return [
            e for e in self._entries if e.round > since_round and e.author != for_author
        ]
