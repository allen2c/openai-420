"""Parse ``OPENAI_PROVIDERS`` into typed per-agent provider configs (the heterogeneous-debate
config). This module is pure parsing — no network, no openai client — so it is fully unit-tested.

``OPENAI_PROVIDERS`` is a comma-separated list of provider URLs, one per agent. Each is
``base_url?<query>`` where the query carries the model, sampling params, role, and rate limits.
Query keys are case-insensitive with ``-`` and ``_`` interchangeable; ``max_tokens`` aliases
``max_completion_tokens``. The last entry is the captain unless an entry sets ``role=captain``.
No value may contain a comma (the list separator). ``api_key`` is a ``SecretStr`` so it never
leaks into a fingerprint or log; ``mask_secrets`` redacts the raw string for the fingerprint.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

_API_KEY_RE = re.compile(r"(?i)(api[_-]?key=)[^&,]*")
_GEN_PARAM_KEYS = ("temperature", "top_p", "reasoning_effort", "max_completion_tokens")


def parse_providers(raw: str) -> list["Provider"]:
    """Parse the ``OPENAI_PROVIDERS`` string into Providers, applying the last=captain default.

    A value containing a comma breaks the split into a malformed entry, which fails validation
    here (missing scheme/model) rather than silently mis-parsing — that is the enforced contract.
    """
    providers: list[Provider] = []
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        url = urlsplit(entry)
        if not url.scheme or not url.netloc:
            raise ValueError(
                f"provider entry is not a full URL (comma in a value?): {entry!r}"
            )
        query = dict(parse_qsl(url.query, keep_blank_values=True))
        providers.append(
            Provider(base_url=f"{url.scheme}://{url.netloc}{url.path}", **query)
        )
    if not providers:
        raise ValueError("OPENAI_PROVIDERS is empty")
    # The last entry leads unless someone was named captain explicitly. A lone provider stays a
    # specialist (the single-model path ignores role anyway).
    if len(providers) > 1 and not any(p.role == "captain" for p in providers):
        providers[-1].role = "captain"
    return providers


def providers_from_env(getenv) -> list["Provider"] | None:
    """The providers from ``OPENAI_PROVIDERS``; ``None`` when it is unset (the single-model path
    still reads the legacy ``OPENAI_MODEL``/... vars). ``getenv`` is ``os.environ.get``.
    """
    raw = getenv("OPENAI_PROVIDERS")
    return parse_providers(raw) if raw and raw.strip() else None


def specialists_and_captain(
    providers: list["Provider"],
) -> tuple[list["Provider"], "Provider"]:
    """Split a roster into (specialists, captain). The captain is the entry tagged ``captain``
    (the last, if several); the rest are specialists."""
    captains = [p for p in providers if p.role == "captain"]
    if not captains:
        raise ValueError("no captain in the provider roster")
    captain = captains[-1]
    specialists = [p for p in providers if p is not captain]
    if not specialists:
        raise ValueError("the roster has a captain but no specialists")
    return specialists, captain


def mask_secrets(raw: str) -> str:
    """Redact ``api_key=...`` in a raw providers string so it is safe to record in a fingerprint."""
    return _API_KEY_RE.sub(r"\1***", raw)


class Provider(BaseModel):
    """One agent's endpoint + model + pinned params, parsed from a provider URL's query."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    base_url: str
    model: str
    api_key: SecretStr = SecretStr("dummy")
    role: Literal["specialist", "captain"] = "specialist"
    name: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    reasoning_effort: str | None = None
    max_completion_tokens: int | None = Field(default=None, alias="max_tokens")
    rpm: int | None = None
    tpm: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_keys(cls, data: object) -> object:
        """Case-insensitive keys with ``-``/``_`` interchangeable, so ``Max-Tokens`` == max_tokens."""
        if not isinstance(data, dict):
            return data
        return {str(k).strip().lower().replace("-", "_"): v for k, v in data.items()}

    @property
    def agent_name(self) -> str:
        """The name teammates address, derived from the model unless ``name=`` overrides it."""
        return self.name or self.model.split("/")[-1].split(":")[0]

    def gen_params(self) -> dict:
        """The pinned inference params to forward to this provider's calls (set keys only)."""
        return {k: v for k in _GEN_PARAM_KEYS if (v := getattr(self, k)) is not None}
