"""Collectors. Each returns a list of doc dicts and never raises on network errors."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Result:
    source: str
    ok: bool
    docs: list[dict] = field(default_factory=list)
    error: str | None = None
    note: str | None = None
