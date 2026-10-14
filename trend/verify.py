"""verify: drop any sentence that fails a check. Nothing is rewritten, only removed.

Checks: citation exists → quote verbatim in cited evidence → no digits →
entity consistency → entailment (separate model call; uncertain = drop).
Links are checked separately; 401/403/WAF are labelled, not removed.
"""
from __future__ import annotations

import json
import logging
import re

from .config import load
from .http import Client
from .llm import LLMError, generate_json

log = logging.getLogger(__name__)
DIGIT = re.compile(r"\d")

ENTAIL = {
    "type": "OBJECT",
    "properties": {"verdicts": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"i": {"type": "INTEGER"},
                       "verdict": {"type": "STRING",
                                   "enum": ["supported", "not_supported", "uncertain"]}},
        "required": ["i", "verdict"]}}},
    "required": ["verdicts"],
}
ENTAIL_SYSTEM = """각 쌍에서 [근거]만 보고 [문장]의 모든 내용이 참이라고 판단할 수 있는지 판정한다.
- 근거에 없는 내용(주체, 시점, 대상, 수식어 포함)이 문장에 하나라도 있으면 not_supported.
- 근거와 문장이 다른 언어여도 의미가 같으면 supported.
- 판단이 애매하면 uncertain."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def evidence_texts(rec: dict) -> list[str]:
    ex = rec["extraction"]
    texts = [rec.get("title", ""), rec.get("summary") or "", ex.get("key_fact_quote") or ""]
    for p in ex.get("products", []):
        texts += [p.get("launch_quote") or "", p.get("notes_quote") or ""]
    return [t for t in texts if t]


def static_checks(s: dict, allowed: set[str], recs: dict[str, dict],
                  known_entities: set[str]) -> str | None:
    """Return a failure reason or None."""
    ids = s.get("doc_ids") or []
    if not ids or any(i not in allowed for i in ids):
        return "citation"
    q = _norm(s.get("quote"))
    if not q or not any(q in _norm(t) for i in ids for t in evidence_texts(recs[i])):
        return "quote_not_verbatim"
    if DIGIT.search(s["text"]):
        return "digits"
    cited = " ".join(_norm(t).lower() for i in ids for t in evidence_texts(recs[i]))
    cited_ents = {e.lower() for i in ids for e in
                  recs[i]["extraction"].get("brands", []) + recs[i]["extraction"].get("companies", [])}
    for e in known_entities:
        el = e.lower()
        if len(el) >= 2 and el in s["text"].lower() and el not in cited and el not in cited_ents:
            return f"entity:{e}"
    return None


def entailment(pairs: list[tuple[str, str]], ledger: str) -> list[str]:
    if not pairs:
        return []
    body = "\n\n".join(f"#{i}\n[근거] {q}\n[문장] {t}" for i, (t, q) in enumerate(pairs))
    try:
        call = generate_json(load("models")["verify"], body, ENTAIL, ENTAIL_SYSTEM, ledger)
    except LLMError as e:
        log.error("entailment failed: %s", e)
        return ["uncertain"] * len(pairs)
    got = {v["i"]: v["verdict"] for v in call.data["verdicts"]}
    return [got.get(i, "uncertain") for i in range(len(pairs))]


def verify_sentences(sents: list[dict], allowed: set[str], recs: dict[str, dict],
                     known_entities: set[str], ledger: str) -> tuple[list[dict], list[dict]]:
    """Returns (kept, log). Every input sentence appears in the log with its outcome."""
    log_rows, survivors = [], []
    for s in sents:
        reason = static_checks(s, allowed, recs, known_entities)
        if reason:
            log_rows.append({**s, "kept": False, "reason": reason})
        else:
            survivors.append(s)
    verdicts = entailment([(s["text"], s["quote"]) for s in survivors], ledger)
    kept = []
    for s, v in zip(survivors, verdicts):
        ok = v == "supported"
        log_rows.append({**s, "kept": ok, "reason": None if ok else f"entailment:{v}"})
        if ok:
            kept.append(s)
    return kept, log_rows


def link_status(urls: list[str]) -> dict[str, str]:
    """ok | restricted (401/402/403/429/WAF challenge/no response) | unverified (other).

    Links are never removed; the label is shown next to them (PLAN).
    """
    client = Client(min_interval=1.0, timeout=20, retries=1)
    out = {}
    for u in sorted(set(urls)):
        r = client.request(u, headers={"Accept": "text/html,application/xhtml+xml"})
        if r.ok:
            out[u] = "ok"
        elif r.status in (401, 402, 403, 202, 429) or r.status is None:
            out[u] = "restricted"
        else:
            out[u] = "unverified"
    return out


def dump(rows) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1)
