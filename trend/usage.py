"""LLM usage from the ledgers: tokens and estimated cost per billing day and model.

Google bills by US Pacific day, so days here are Pacific too (KST is 16-17 h ahead).
Ledgers: data/llm_ledger/*.jsonl (enrich), data/reports/*/*/llm_calls.jsonl (report runs),
usage/*.jsonl (calls made in work sessions outside Actions, committed by hand).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import store
from .config import ROOT, load

PACIFIC = ZoneInfo("America/Los_Angeles")


def ledger_files() -> list[Path]:
    d = store.data_dir()
    return (sorted((d / "llm_ledger").glob("*.jsonl")) + sorted((d / "reports").glob("*/*/llm_calls.jsonl"))
            + sorted((ROOT / "usage").glob("*.jsonl")))


def rows(since: str | None = None) -> dict:
    out = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "think": 0})
    seen = set()
    for f in ledger_files():
        for line in f.read_text("utf-8").splitlines():
            if not line.strip() or line in seen:      # the same line copied into usage/ counts once
                continue
            seen.add(line)
            r = json.loads(line)
            if "in" not in r:
                continue
            day = datetime.fromisoformat(r["ts"]).astimezone(PACIFIC).date().isoformat()
            if since and day < since:
                continue
            a = out[(day, r["model"])]
            a["calls"] += 1
            for k in ("in", "out", "think"):
                a[k] += r.get(k, 0)
    return out


def summarize(since: str | None = None) -> str:
    krw = load("models")["enrich"].get("krw_per_1k_tokens", 1.9)
    lines = ["day(PT)     model                 calls     tokens   est.KRW(flash rate)"]
    for (day, model), a in sorted(rows(since).items()):
        tok = a["in"] + a["out"] + a["think"]
        cost = f"{tok / 1000 * krw:>8.0f}" if "flash" in model else "       -"
        lines.append(f"{day}  {model:<20} {a['calls']:>6} {tok:>10} {cost}")
    return "\n".join(lines)
