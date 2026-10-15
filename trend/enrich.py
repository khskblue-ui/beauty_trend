"""enrich: per-article structured extraction with Gemini Flash.

Every extracted claim must carry a verbatim quote from the article; quotes are
checked in code (substring after whitespace normalization) and claims without a
valid quote are dropped. Numbers are never taken from the LLM for the report.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from . import store
from .config import load
from .llm import LLMError, generate_json
from .util import kst_date, utcnow_iso

log = logging.getLogger(__name__)
PROMPT_VERSION = "enrich-v2"   # v2: launch_status (2026-10-15)
CATEGORIES = ["fragrance", "skincare", "makeup", "hair", "body", "ingredient",
              "regulation", "business", "retail", "other"]
EVENTS = ["product_launch", "business", "regulation", "market_trend", "ingredient",
          "event", "other"]

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "relevant": {"type": "BOOLEAN"},
        "category": {"type": "STRING", "enum": CATEGORIES},
        "event_type": {"type": "STRING", "enum": EVENTS},
        "countries": {"type": "ARRAY", "items": {"type": "STRING"}},
        "brands": {"type": "ARRAY", "items": {"type": "STRING"}},
        "companies": {"type": "ARRAY", "items": {"type": "STRING"}},
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "is_press_release": {"type": "BOOLEAN"},
        "products": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "brand": {"type": "STRING", "nullable": True},
                "launch_date": {"type": "STRING", "nullable": True},
                "launch_status": {"type": "STRING", "enum": ["launched", "upcoming", "unknown"]},
                "launch_quote": {"type": "STRING", "nullable": True},
                "notes": {"type": "ARRAY", "items": {"type": "STRING"}},
                "notes_quote": {"type": "STRING", "nullable": True},
            },
            "required": ["name", "brand", "launch_date", "launch_status", "launch_quote", "notes",
                         "notes_quote"],
        }},
        "key_fact": {"type": "STRING", "nullable": True},
        "key_fact_quote": {"type": "STRING", "nullable": True},
    },
    "required": ["relevant", "category", "event_type", "countries", "brands", "companies",
                 "keywords", "is_press_release", "products", "key_fact", "key_fact_quote"],
}

SYSTEM = """너는 향료 회사 영업팀을 위한 뷰티·향료 업계 기사 분석기다.
규칙:
- 기사에 명시된 내용만 추출한다. 추측·일반 상식 보완 금지.
- *_quote 필드에는 기사 원문을 한 글자도 바꾸지 말고 그대로 복사한다(200자 이내, 한 문장 위주). 근거가 없으면 null.
- 향 노트(notes)는 기사에 향/노트/향조로 명시된 것만. 없으면 빈 배열.
- launch_date는 기사에 출시일·출시 시점이 명시된 경우만 YYYY-MM-DD 또는 YYYY-MM. '최근', '이달' 같은 표현은 기사 게시일을 기준으로 해석하지 말고 null.
- launch_status: 기사가 이 제품을 새로 출시했다고 보도하면(출시했다·선보였다·론칭했다·내놨다) launched, 출시 예정이면 upcoming, 기존 제품 소개·판매 순위·과거 출시 언급이면 unknown.
- launch_quote: 출시(또는 출시 예정)를 말하는 원문 문장. launched·upcoming이면 반드시 채운다.
- keywords: 이 기사가 보여 주는 업계 트렌드 용어 2~5개를 한국어 명사구로(예: '니치 향수', '비건 뷰티', '바디 미스트'). 브랜드명·회사명은 넣지 않는다.
- relevant: 화장품·향수·향료·뷰티 산업과 직접 관련이면 true. '향수(鄕愁)' 같은 동음이의어나 무관한 기사면 false.
- is_press_release: 특정 기업이 배포한 신제품·실적 홍보성 보도자료로 보이면 true.
- countries: 관련 국가 ISO 3166-1 alpha-2 코드.
- key_fact: 기사의 핵심 사실 한 문장을 한국어로 요약(숫자 금지). key_fact_quote는 그 근거 원문."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def quote_ok(quote: str | None, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and len(q) <= 400 and q in _norm(text)


def source_text(doc: dict) -> str:
    from .collect.article import clean_body
    body = clean_body(store.load_body(doc["doc_id"])) or ""
    return "\n".join(x for x in (doc["title"], doc.get("summary", ""), body) if x)


def check(ex: dict, text: str) -> dict:
    """Drop claims whose quotes are not verbatim in the source text."""
    dropped = []
    products = []
    for p in ex.get("products", []):
        if not quote_ok(p.get("launch_quote"), text):
            if p.get("launch_date") or p.get("launch_status") in ("launched", "upcoming"):
                dropped.append(f"launch:{p['name']}")
            p["launch_date"], p["launch_quote"] = None, None
            p["launch_status"] = "unknown"
        if p.get("notes"):
            ok_quote = quote_ok(p.get("notes_quote"), text)
            kept = [n for n in p["notes"] if ok_quote and _norm(n) and _norm(n) in _norm(p["notes_quote"])]
            if len(kept) < len(p["notes"]):
                dropped.append(f"notes:{p['name']}")
            p["notes"] = kept
            if not kept:
                p["notes_quote"] = None
        if _norm(p.get("name")) and _norm(p["name"]).lower() in _norm(text).lower():
            products.append(p)
        else:
            dropped.append(f"product:{p.get('name')}")
    ex["products"] = products
    if not quote_ok(ex.get("key_fact_quote"), text):
        if ex.get("key_fact"):
            dropped.append("key_fact")
        ex["key_fact"], ex["key_fact_quote"] = None, None
    ex["brands"] = [b for b in ex.get("brands", []) if _norm(b).lower() in _norm(text).lower()]
    ex["dropped"] = dropped
    return ex


def enrich_doc(doc: dict, ledger: str | None = None) -> dict | None:
    text = source_text(doc)
    prompt = (f"[출처] {doc['source_name']}\n[게시일] {doc.get('published_at')}\n"
              f"[제목] {doc['title']}\n[본문]\n{text[:6000]}")
    try:
        call = generate_json(load("models")["enrich"], prompt, SCHEMA, SYSTEM, ledger)
    except LLMError as e:
        log.warning("enrich failed %s: %s", doc["doc_id"], e)
        return None
    ex = check(call.data, text)
    meta = {k: doc.get(k) for k in ("doc_id", "source", "source_name", "group", "lang", "url",
                                     "title", "summary", "published_at", "date_source", "evidence_grade",
                                     "query", "doc_type", "celex")}
    return {**meta, "extraction": ex, "model": call.model, "prompt_version": PROMPT_VERSION,
            "enriched_at": utcnow_iso(), "had_body": bool(store.load_body(doc["doc_id"]))}


def doc_month(doc: dict) -> str:
    d = kst_date(doc.get("published_at")) or kst_date(doc.get("fetched_at"))
    return f"{d.year:04d}-{d.month:02d}"


def enrich_pending(month: str | None = None, limit: int | None = None,
                   workers: int = 4) -> dict:
    """Enrich raw docs that have no enriched record yet (optionally one month)."""
    root = store.data_dir() / "enriched"
    done = {p.stem for p in root.glob("*/*.json")} if root.exists() else set()
    todo = [d for d in store.iter_raw() if d["doc_id"] not in done
            and (month is None or doc_month(d) == month)]
    todo = list({d["doc_id"]: d for d in todo}.values())[:limit]
    ledger = str(store.data_dir() / "llm_ledger" / f"{utcnow_iso()[:7]}.jsonl")
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for d, rec in zip(todo, pool.map(lambda x: enrich_doc(x, ledger), todo)):
            if rec is None:
                fail += 1
                continue
            store.write_json(f"enriched/{doc_month(d)}/{d['doc_id']}.json", rec)
            ok += 1
    return {"pending": len(todo), "enriched": ok, "failed": fail}
