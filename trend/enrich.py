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
from .llm import LLMError, PendingLLM, generate_json
from .util import kst_date, now_kst, utcnow_iso

log = logging.getLogger(__name__)
PROMPT_VERSION = "enrich-v3"   # v2: launch_status; v3: events, ingredients (2026-10-15)
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
        "events": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "start_date": {"type": "STRING"},
                "end_date": {"type": "STRING", "nullable": True},
                "place": {"type": "STRING", "nullable": True},
                "quote": {"type": "STRING"},
            },
            "required": ["name", "start_date", "end_date", "place", "quote"],
        }},
        "ingredients": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}, "quote": {"type": "STRING"}},
            "required": ["name", "quote"],
        }},
    },
    "required": ["relevant", "category", "event_type", "countries", "brands", "companies",
                 "keywords", "is_press_release", "products", "key_fact", "key_fact_quote",
                 "events", "ingredients"],
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
- key_fact: 기사의 핵심 사실 한 문장을 한국어로 요약(숫자 금지). key_fact_quote는 그 근거 원문.
- events: 기사에 날짜가 적힌 업계 행사(박람회, 전시회, 신제품 발표회, 세미나, 시상식, 팝업스토어). 날짜가 없으면 넣지 않는다.
  start_date와 end_date는 YYYY-MM-DD. 원문에 연도가 없으면 게시일의 연도로 쓴다. 하루 행사면 end_date는 null.
  name은 원문의 행사 이름, place는 원문에 적힌 장소(없으면 null), quote는 날짜가 들어 있는 원문 문장.
- ingredients: 기사에 이름이 나온 화장품 원료나 성분, 향료 원료(성분명, 소재명). '원료', '성분' 같은 일반어는 넣지 않는다.
  name은 원문 표기 그대로, quote는 그 이름이 들어 있는 원문 문장."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def quote_ok(quote: str | None, text: str) -> bool:
    q = _norm(quote)
    return bool(q) and len(q) <= 400 and q in _norm(text)


def source_text(doc: dict) -> str:
    from .collect.article import clean_body
    body = clean_body(store.load_body(doc["doc_id"])) or ""
    return "\n".join(x for x in (doc["title"], doc.get("summary", ""), body) if x)


GENERIC_INGREDIENT = {"원료", "성분", "소재", "천연 원료", "원료 소재", "유효 성분", "향료", "추출물"}


def _event_ok(e: dict, text: str) -> bool:
    """Verbatim quote, ISO dates, and the start day number written in the quote."""
    from datetime import date
    if not quote_ok(e.get("quote"), text) or not _norm(e.get("name")):
        return False
    try:
        start = date.fromisoformat(e.get("start_date") or "")
        if e.get("end_date"):
            if date.fromisoformat(e["end_date"]) < start:
                return False
    except ValueError:
        return False
    return re.search(rf"(?<!\d){start.day}(?!\d)", e["quote"]) is not None


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
    ex["events"] = [e for e in ex.get("events", []) if _event_ok(e, text)]
    ex["ingredients"] = [g for g in ex.get("ingredients", [])
                         if quote_ok(g.get("quote"), text) and _norm(g.get("name")).lower() in _norm(g["quote"]).lower()
                         and _norm(g["name"]) not in GENERIC_INGREDIENT]
    ex["dropped"] = dropped
    return ex


def enrich_doc(doc: dict, ledger: str | None = None) -> dict | None:
    text = source_text(doc)
    prompt = (f"[출처] {doc['source_name']}\n[게시일] {doc.get('published_at')}\n"
              f"[제목] {doc['title']}\n[본문]\n{text[:6000]}")
    try:
        call = generate_json(load("models")["enrich"], prompt, SCHEMA, SYSTEM, ledger)
    except PendingLLM:
        return "pending"
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


def estimate(n_docs: int) -> dict:
    """Expected cost of enriching n_docs, from config (2026-10 billing)."""
    cfg = load("models")["enrich"]
    tokens = n_docs * cfg.get("tokens_per_doc", 1100)
    return {"docs": n_docs, "tokens": tokens,
            "krw": round(tokens / 1000 * cfg.get("krw_per_1k_tokens", 1.9))}


# Same news in several outlets: enrich one, copy its classification to the rest (no LLM call).
COPY_FIELDS = ("relevant", "category", "event_type", "countries", "brands", "companies",
               "keywords", "is_press_release")


class DupIndex:
    """Articles by KST day, to find the same news within ±days (title bigram similarity)."""

    def __init__(self, days: int = 3):
        self.days, self.by_day = days, {}

    def add(self, rec: dict) -> None:
        d = kst_date(rec.get("published_at"))
        if d:
            self.by_day.setdefault(d, []).append(rec)

    def find(self, doc: dict) -> dict | None:
        from datetime import timedelta
        from .normalize import similar
        d0 = kst_date(doc.get("published_at"))
        if not d0:
            return None
        for k in range(-self.days, self.days + 1):
            for r in self.by_day.get(d0 + timedelta(days=k), []):
                if similar(doc["title"], r["title"]):
                    return r
        return None


def copy_record(doc: dict, rep: dict) -> dict:
    """Record for a near-duplicate article: classification copied, no claims.

    Products, events, ingredients and key facts need quotes from THIS article, so
    they stay empty; the cluster's representative carries them.
    """
    ex = {k: rep["extraction"].get(k) for k in COPY_FIELDS}
    ex.update(products=[], events=[], ingredients=[], key_fact=None, key_fact_quote=None, dropped=[])
    meta = {k: doc.get(k) for k in ("doc_id", "source", "source_name", "group", "lang", "url",
                                     "title", "summary", "published_at", "date_source", "evidence_grade",
                                     "query", "doc_type", "celex")}
    return {**meta, "extraction": ex, "model": None, "prompt_version": PROMPT_VERSION,
            "copied_from": rep["doc_id"], "enriched_at": utcnow_iso(),
            "had_body": bool(store.load_body(doc["doc_id"]))}


def enrich_pending(month: str | None = None, limit: int | None = None,
                   workers: int = 4, upgrade: bool = False, yes: bool = False) -> dict:
    """Enrich raw docs that have no enriched record yet (optionally one month).

    upgrade=True also redoes docs enriched with an older PROMPT_VERSION.
    Near-duplicates of an already enriched article get a copied record instead
    of an LLM call. When the estimated cost is above `confirm_over_krw`, nothing
    runs without yes=True (the estimate is returned).
    """
    root = store.data_dir() / "enriched"
    done = set()
    for p in (root.glob("*/*.json") if root.exists() else []):
        if not upgrade or (store.read_json(p, {}) or {}).get("prompt_version") == PROMPT_VERSION:
            done.add(p.stem)
    todo = [d for d in store.iter_raw() if d["doc_id"] not in done
            and (month is None or doc_month(d) == month)]
    todo = list({d["doc_id"]: d for d in todo}.values())[:limit]
    # split: one article per news item goes to the LLM; the rest copy from it
    enriched = [r for r in (store.read_json(p, {}) for p in (root.glob("*/*.json") if root.exists() else []))
                if r and r["doc_id"] in done and not r.get("copied_from")]
    idx = DupIndex()
    for r in enriched:
        idx.add(r)
    calls, copies = [], []
    for d in sorted(todo, key=lambda x: x.get("published_at") or ""):
        rep = idx.find(d)
        if rep:
            copies.append((d, rep))
        else:
            calls.append(d)
            idx.add(d)
    est = estimate(len(calls))
    paid = load("models")["enrich"].get("backend", "gemini") != "session"
    if paid and (upgrade or est["krw"] > load("models")["enrich"].get("confirm_over_krw", 3000)) and not yes:
        return {"pending": len(todo), "llm_calls": len(calls), "copies": len(copies),
                "estimate": est, "ran": False, "note": "예상 금액이 기준을 넘어 멈춤. --yes로 실행"}
    ledger = str(store.data_dir() / "llm_ledger" / f"{now_kst():%Y-%m}.jsonl")
    ok = fail = waiting = 0
    done_recs: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for d, rec in zip(calls, pool.map(lambda x: enrich_doc(x, ledger), calls)):
            if rec == "pending":          # session backend: request written, answer not in yet
                waiting += 1
                continue
            if rec is None:
                fail += 1
                continue
            store.write_json(f"enriched/{doc_month(d)}/{d['doc_id']}.json", rec)
            done_recs[d["doc_id"]] = rec
            ok += 1
    by_id = {r["doc_id"]: r for r in enriched} | done_recs
    copied = 0
    for d, rep in copies:
        rec = by_id.get(rep["doc_id"])
        if rec is None:          # its representative failed: try again next run
            continue
        store.write_json(f"enriched/{doc_month(d)}/{d['doc_id']}.json", copy_record(d, rec))
        copied += 1
    return {"pending": len(todo), "enriched": ok, "copied": copied, "failed": fail,
            "waiting_for_answers": waiting, "estimate": est if paid else None, "ran": True}
