"""Orchestrator — the abstract control loop every system implements (PRINCIPLES Law 2).

An orchestrator turns one user query into one final answer. That is the whole contract:
``run`` is a coroutine taking the (already format-instructed) prompt and returning the
deliverable to grade — the answer alone, with any reasoning stripped. Subclasses own the
mechanism (a single call, parallel consensus, ...); the harness depends only on ``run``.

Many variants live side by side and old ones are never deleted (see the orchestrators
package), so each registers under a stable name stating its mechanism via ``@register`` and
the harness dispatches by that name. ``from_args`` is the uniform factory: it receives the
harness's known knobs as keyword options and each orchestrator picks the ones it needs, so
adding a system is "write the class, register it" — run.py never grows a branch per system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

import openai

_REGISTRY: dict[str, type["Orchestrator"]] = {}


def register(name: str) -> Callable[[type], type]:
    """Class decorator: bind ``name`` to an Orchestrator subclass for harness dispatch."""

    def decorator(cls: type) -> type:
        if name in _REGISTRY:
            raise ValueError(f"orchestrator name already registered: {name!r}")
        _REGISTRY[name] = cls
        return cls

    return decorator


def get(name: str) -> type["Orchestrator"]:
    """The registered orchestrator class for ``name`` (KeyError if unknown)."""
    return _REGISTRY[name]


def names() -> list[str]:
    """Registered orchestrator names, sorted — the harness's ``--system`` choices."""
    return sorted(_REGISTRY)


class Orchestrator(ABC):
    @classmethod
    def from_args(
        cls,
        *,
        client: openai.AsyncOpenAI,
        model: str,
        gen_params: dict,
        **options,
    ) -> "Orchestrator":
        """Build from the harness's knobs. The default uses only the shared three; a
        subclass overrides to read the ``options`` it needs (e.g. ``group``)."""
        return cls(client=client, model=model, gen_params=gen_params)

    @abstractmethod
    async def run(self, user_query: str) -> str:
        """Answer one query, returning the final deliverable (reasoning stripped)."""
