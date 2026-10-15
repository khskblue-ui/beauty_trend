"""write: Gemini (write model) turns evidence cards into cited sentences.

The model may only use the cards it is given. Each sentence carries doc_ids and a
verbatim quote copied from a card; numbers are forbidden (verify drops them).
"""
from __future__ import annotations

import json
import logging

from .config import load
from .llm import LLMError, generate_json

log = logging.getLogger(__name__)
PROMPT_VERSION = "write-v4"  # v2: one card per sentence; v3: style rules; v4: plain-korean-writing rules

SENTENCES = {
    "type": "OBJECT",
    "properties": {"sentences": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"text": {"type": "STRING"},
                       "doc_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
                       "quote": {"type": "STRING"}},
        "required": ["text", "doc_ids", "quote"]}}},
    "required": ["sentences"],
}
KEYWORDS = {
    "type": "OBJECT",
    "properties": {"items": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"term": {"type": "STRING"}, "text": {"type": "STRING"},
                       "doc_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
                       "quote": {"type": "STRING"}},
        "required": ["term", "text", "doc_ids", "quote"]}}},
    "required": ["items"],
}

SYSTEM = """너는 향료 회사 영업 담당자가 상사에게 제출할 월간 업계 리포트의 문장을 쓴다.
절대 규칙:
1. 제공된 근거 카드에 있는 사실만 쓴다. 카드에 없는 배경지식, 전망, 평가, 소비자 반응은 쓰지 않는다.
2. 한 문장은 근거 카드 하나의 사실만 쓴다. 여러 카드의 사실을 한 문장에 합치지 않는다. doc_ids에는 그 카드의 doc_id 하나를 넣고, quote에는 같은 카드의 quote(또는 title)에서 문장 전체를 뒷받침하는 부분을 한 글자도 바꾸지 말고 복사한다.
3. 숫자(아라비아 숫자)를 쓰지 않는다. 금액, 비율, 날짜, 순위, 개수는 모두 생략한다.
4. "~할 것으로 보인다", "주목된다", "기대된다" 같은 해석이나 전망 표현을 쓰지 않는다. 사실을 평서문으로 쓴다.
5. 한 문장은 80자 안팎의 한국어 보도 문체(~했다/~이다)로 쓴다. 영어 근거는 직역하지 말고 국내 업계지 기자가 쓰듯 옮긴다.
6. 근거 등급이 headline인 카드는 제목 수준 사실만 쓴다.
7. 보도자료의 홍보 문구(혁신, 독보적, 본연의 등)는 옮기지 않는다. 회사가 한 일만 쓴다.
8. 문장 첫머리에 누가 무엇을 했는지 이름을 댄다. 회사, 브랜드, 제품, 기관 이름을 '이 회사', '해당 제품'처럼 가리키는 말로 바꾸지 않는다.
9. 사물이나 시장에 사람의 동작을 붙이지 않고, 은유로 돌려 말하지 않는다. 업계에서 쓰는 말은 그대로 쓴다.
10. 같은 문장 틀을 여러 문장에 되풀이하지 않는다. 문장마다 그 사실에 맞는 동사를 고른다.
문체 규칙:
"""


def system_prompt() -> str:
    from .style import prompt_rules
    return SYSTEM + prompt_rules()


def _cards(cards: list[dict]) -> str:
    keep = ("doc_id", "source_name", "published", "evidence_grade", "title", "key_fact", "quote")
    return json.dumps([{k: c.get(k) for k in keep} for c in cards], ensure_ascii=False, indent=1)


def sentences(task: str, cards: list[dict], max_sentences: int, ledger: str) -> list[dict]:
    if not cards:
        return []
    prompt = (f"[작업] {task}\n최대 {max_sentences}문장. 중요도가 높은 사실부터.\n"
              f"[근거 카드]\n{_cards(cards)}")
    try:
        call = generate_json(load("models")["write"], prompt, SENTENCES, system_prompt(), ledger)
    except LLMError as e:
        log.error("write failed (%s): %s", task[:30], e)
        return []
    return [{**s, "model": call.model} for s in call.data["sentences"][:max_sentences]]


def keyword_notes(items: list[dict], cards_by_term: dict[str, list[dict]], ledger: str) -> list[dict]:
    if not items:
        return []
    blocks = "\n\n".join(f"### 키워드: {it['term']}\n{_cards(cards_by_term[it['term']])}"
                         for it in items)
    prompt = ("[작업] 각 키워드가 이번 달 업계 기사에서 어떤 사실과 함께 등장했는지 키워드마다 한 문장으로 쓴다. "
              "term은 주어진 키워드를 그대로 쓴다.\n" + blocks)
    try:
        call = generate_json(load("models")["write"], prompt, KEYWORDS, system_prompt(), ledger)
    except LLMError as e:
        log.error("write keywords failed: %s", e)
        return []
    return [{**s, "model": call.model} for s in call.data["items"]]
