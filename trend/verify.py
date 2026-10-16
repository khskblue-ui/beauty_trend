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
from .llm import LLMError, PendingLLM, generate_json

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
    if rec.get("group") == "regulation":
        # an official board's name says who issued it (titles often omit the agency)
        texts.append(rec.get("source_name") or "")
    for p in ex.get("products", []):
        texts += [p.get("launch_quote") or "", p.get("notes_quote") or ""]
    return [t for t in texts if t]


def static_checks(s: dict, allowed: set[str], recs: dict[str, dict],
                  known_entities: set[str], variants=None) -> str | None:
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
        if len(el) < 2 or el not in s["text"].lower():
            continue
        spellings = {x.lower() for x in (variants(e) if variants else {e})}
        if not any(x in cited or x in cited_ents for x in spellings):
            return f"entity:{e}"
    return None


def entailment(pairs: list[tuple[str, str]], ledger: str) -> list[str]:
    if not pairs:
        return []
    body = "\n\n".join(f"#{i}\n[근거] {q}\n[문장] {t}" for i, (t, q) in enumerate(pairs))
    try:
        call = generate_json(load("models")["verify"], body, ENTAIL, ENTAIL_SYSTEM, ledger)
    except PendingLLM:
        return ["pending"] * len(pairs)      # session backend: answer not in yet (not a verdict)
    except LLMError as e:
        log.error("entailment failed: %s", e)
        return ["uncertain"] * len(pairs)
    got = {v["i"]: v["verdict"] for v in call.data["verdicts"]}
    return [got.get(i, "uncertain") for i in range(len(pairs))]


def verify_sentences(sents: list[dict], allowed: set[str], recs: dict[str, dict],
                     known_entities: set[str], ledger: str,
                     variants=None) -> tuple[list[dict], list[dict]]:
    """Returns (kept, log). Every input sentence appears in the log with its outcome."""
    log_rows, survivors = [], []
    for s in sents:
        reason = static_checks(s, allowed, recs, known_entities, variants)
        if reason:
            log_rows.append({**s, "kept": False, "reason": reason})
        else:
            survivors.append(s)
    # evidence = the cited articles' titles + the quote: the subject (company, brand) is
    # usually in the title, not in the quoted sentence
    def evidence(s):
        titles = " / ".join(recs[i].get("title", "") for i in s["doc_ids"] if i in recs)
        return f"(기사 제목) {titles}\n(인용) {s['quote']}"
    verdicts = entailment([(s["text"], evidence(s)) for s in survivors], ledger)
    kept = []
    for s, v in zip(survivors, verdicts):
        ok = v == "supported"
        log_rows.append({**s, "kept": ok, "reason": None if ok else f"entailment:{v}"})
        if ok:
            kept.append(s)
    return kept, log_rows


def _context(text: str, quote: str | None, width: int = 400) -> str:
    """The quote with the text around it (the product name is often a sentence earlier)."""
    t, q = _norm(text), _norm(quote)
    i = t.find(q) if q else -1
    if i < 0:
        return t[: width * 2]
    return t[max(0, i - width): i + len(q) + width]


def _check_key(it: dict, kind: str) -> str:
    return "|".join([it["doc_id"], kind, it.get("brand") or "", it["name"], ",".join(it.get("notes") or [])])


def _check_cache() -> tuple[dict, "Path"]:
    from . import store
    path = store.data_dir() / "checks" / "products.json"
    return store.read_json(path, {}) or {}, path


def verify_products(items: list[dict], kind: str, recs: dict[str, dict], ledger: str,
                    variants=None) -> tuple[list[dict], list[dict]]:
    """Product rows (notes / launches): brand required and named in the article, then
    an entailment check that the article ties this brand + product to the claim.

    kind "notes": claim = product uses these notes; "launch": claim = product launched.
    Verdicts are cached in DATA_DIR/checks/products.json (committed; no article text).
    The daily session checks new articles while their bodies are on disk
    (`trend check-products`); the monthly report reuses those verdicts.
    """
    from . import store
    from .enrich import source_text
    cache, cache_path = _check_cache()
    rows, cand, pairs = [], [], []
    todo = []
    for it in items:
        hit = cache.get(_check_key(it, kind))
        if hit:
            rows.append({**it, "kind": kind, "kept": hit["kept"], "reason": hit["reason"], "cached": True})
        else:
            todo.append(it)
    for it in todo:
        rec = recs.get(it["doc_id"])
        brand = (it.get("brand") or "").strip()
        if not brand:
            rows.append({**it, "kind": kind, "kept": False, "reason": "no_brand"})
            continue
        text = source_text(rec) if rec else ""
        spellings = variants(brand) if variants else {brand}
        if not any(_norm(s).lower() in _norm(text).lower() for s in spellings):
            rows.append({**it, "kind": kind, "kept": False, "reason": "brand_not_in_article"})
            continue
        if kind == "notes":
            claim = f"{brand}의 '{it['name']}' 제품에는 {', '.join(it['notes'])} 향 노트가 쓰였다."
        else:
            claim = f"{brand}이(가) '{it['name']}' 제품을 출시했다."
        ev = f"{rec.get('title', '')}\n{_context(text, it.get('quote'))}"
        cand.append(it)
        pairs.append((claim, ev))
    verdicts = [v for i in range(0, len(pairs), 20) for v in entailment(pairs[i:i + 20], ledger)]
    for it, v, (claim, _) in zip(cand, verdicts, pairs):
        ok = v == "supported"
        rows.append({**it, "kind": kind, "claim": claim, "kept": ok,
                     "reason": None if ok else f"entailment:{v}"})
    for r in rows:
        if not r.get("cached") and r["reason"] != "entailment:pending":
            cache[_check_key(r, kind)] = {"kept": r["kept"], "reason": r["reason"]}
    store._write_json(cache_path, cache)
    kept = [it for it in items if any(r["kept"] and _check_key(r, kind) == _check_key(it, kind) for r in rows)]
    return kept, rows


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


def check_products(recs: list[dict], ledger: str | None = None) -> dict:
    """Daily: verdicts for the notes/launch claims of new articles while their bodies are
    on disk. Already-cached claims are skipped; pending answers are not cached."""
    from .aggregate import product_claims
    from .normalize import Entities
    ents = Entities()
    by_id = {r["doc_id"]: r for r in recs}
    totals = {"notes": 0, "launch": 0}
    pending = 0
    for kind in ("notes", "launch"):
        items = [it for r in recs for it in product_claims(r, ents)[kind]]
        _, rows = verify_products(items, kind, by_id, ledger, ents.variants)
        totals[kind] = len(items)
        pending += sum(r["reason"] == "entailment:pending" for r in rows)
    return {"claims": totals, "waiting_for_answers": pending}
