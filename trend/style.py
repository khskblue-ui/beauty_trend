"""Korean report style: lint LLM sentences against config/style.yaml and rewrite
flagged ones with the write model.

Rewrites only change wording. doc_ids and quote stay as they were, and every
rewritten sentence goes through verify again, so a rewrite cannot add facts.
"""
from __future__ import annotations

import json
import logging
import re

from .config import load
from .llm import LLMError, PendingLLM, generate_json

log = logging.getLogger(__name__)
PROMPT_VERSION = "style-v2"   # v2: plain-korean-writing rules

REWRITE = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"i": {"type": "INTEGER"}, "text": {"type": "STRING"}},
        "required": ["i", "text"]}}},
    "required": ["items"],
}

REWRITE_SYSTEM = """너는 국내 업계 리포트의 교열 기자다. 문장을 자연스러운 한국어 보도 문장으로 고친다.
규칙:
- 사실(주체, 대상, 행동, 시점)은 바꾸지 않는다. 새 정보를 더하지 않고, 근거에 없는 말을 넣지 않는다.
- [지적]에 걸린 말만 고친다. 걸리지 않은 부분은 그대로 둔다.
- 숫자를 쓰지 않는다.
- 각 문장에 붙은 [지적]을 모두 해결한다.
- ~했다/~이다로 끝나는 짧은 평서문. 한 문장 80자 안팎.
- 회사, 브랜드, 제품 이름은 그대로 둔다. 가운뎃점과 줄표를 쓰지 않는다."""


def rules() -> list[dict]:
    return load("style")["sentence_rules"]


PARTICLE = re.compile(r"(은|는|이|가|을|를|과|와|의|에|에서|에게|으로|로|도|만|까지|부터|이다|이며|하고)$")


def repeated_words(text: str, min_len: int) -> list[str]:
    """Content words (particles stripped) that occur more than once in a sentence."""
    seen, dup = set(), []
    for tok in re.findall(r"[가-힣A-Za-z]+", text):
        w = PARTICLE.sub("", tok)
        if len(w) < min_len:
            continue
        if w in seen and w not in dup:
            dup.append(w)
        seen.add(w)
    return dup


def lint(text: str) -> list[dict]:
    """Return the rules a sentence violates (id + hint)."""
    out = []
    for r in rules():
        if "pattern" in r and re.search(r["pattern"], text):
            out.append({"id": r["id"], "hint": r["hint"]})
        elif "count_pattern" in r and len(re.findall(r["count_pattern"], text)) > r["max_count"]:
            out.append({"id": r["id"], "hint": r["hint"]})
        elif "repeat_min_len" in r and (dup := repeated_words(text, r["repeat_min_len"])):
            out.append({"id": r["id"], "hint": f"{r['hint']} 되풀이된 말: {', '.join(dup)}"})
    return out


def prompt_rules() -> str:
    """Style rules as prompt text for the write model (same source as the lint)."""
    return "\n".join(f"- {r['hint']}" for r in rules())


def polish(sents: list[dict], ledger: str, key: str = "text") -> tuple[list[dict], list[dict]]:
    """Rewrite sentences that fail the lint. Returns (sentences, style_log).

    Each returned sentence keeps doc_ids/quote; `original` holds the pre-rewrite
    text when it changed. Sentences the model fails to fix keep their lint hits.
    """
    flagged = [(i, s, lint(s[key])) for i, s in enumerate(sents)]
    flagged = [(i, s, hits) for i, s, hits in flagged if hits]
    if not flagged:
        return sents, []
    body = "\n\n".join(
        f"#{i}\n[문장] {s[key]}\n[근거] {s.get('quote', '')}\n[지적] " + " / ".join(h["hint"] for h in hits)
        for i, s, hits in flagged)
    try:
        call = generate_json(load("models")["write"], body, REWRITE, REWRITE_SYSTEM, ledger)
        fixed = {x["i"]: x["text"].strip() for x in call.data["items"]}
    except LLMError as e:
        (log.info if isinstance(e, PendingLLM) else log.warning)("style rewrite: %s", e)
        fixed = {}
    out = list(sents)
    slog = []
    for i, s, hits in flagged:
        new = fixed.get(i)
        if new and new != s[key]:
            out[i] = {**s, key: new, "original": s[key]}
        remaining = lint(out[i][key])
        slog.append({"before": s[key], "after": out[i][key], "hits": [h["id"] for h in hits],
                     "remaining": [h["id"] for h in remaining]})
    return out, slog


def copy_violations(text: str) -> list[str]:
    """Banned reader-facing words found in template copy."""
    return [w for w in load("style")["copy_banned"] if w in text]


def dump(rows) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1)
