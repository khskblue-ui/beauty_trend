"""aggregate: every number in the report is computed here, never by the LLM."""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from . import datalab
from .config import load
from .normalize import Cluster, Entities, similar
from .util import kst_date, month_bounds

log = logging.getLogger(__name__)
MARKET_EVENTS = {"business", "market_trend", "retail", "event", "ingredient"}


def _kw(s: str) -> str:
    """Grouping key: spacing variants of a term are the same term (더마 코스메틱 = 더마코스메틱)."""
    return re.sub(r"\s+", "", s).lower()


def _nospace(s: str) -> str:
    """Spacing, case and apostrophe style ignored ('L’Entropiste' = 'L'Entropiste')."""
    return re.sub(r"[\s'’‘`]+", "", s).lower()


def doc_keywords(d: dict, stop: set[str]) -> set[str]:
    """Keywords counted for one doc.

    Generic category words are dropped. For docs found through NAVER news
    search, keywords that echo the search query are dropped too — otherwise the
    query list itself would show up as this month's trend.
    """
    q = _nospace(d.get("query") or "")
    out = set()
    for k in d["extraction"].get("keywords", []):
        key = _kw(k)
        ns = _nospace(k)
        if not ns or ns in stop:
            continue
        if q and (q in ns or ns in q):
            continue
        out.add(key)
    return out


def keywords(clusters: list[Cluster], prev: list[Cluster], cfg: dict,
             stoplist: list[str] | None = None) -> dict:
    """Terms ranked by distinct-cluster count (growth vs previous month if available)."""
    stop = {_nospace(x) for x in (stoplist or [])}
    cur, before = defaultdict(set), Counter()
    label: dict[str, Counter] = defaultdict(Counter)
    for c in clusters:
        for d in c.docs:
            raw = {_kw(k): k.strip() for k in d["extraction"].get("keywords", [])}
            for key in doc_keywords(d, stop):
                cur[key].add(c.cid)
                label[key][raw[key]] += 1
    for c in prev:
        for k in {k for d in c.docs for k in doc_keywords(d, stop)}:
            before[k] += 1
    min_c = cfg["min_clusters_per_item"]
    has_prev = bool(prev)
    items = []
    for k, cids in cur.items():
        if len(cids) < min_c:
            continue
        items.append({"term": label[k].most_common(1)[0][0], "key": k,
                      "clusters": sorted(cids), "n_clusters": len(cids),
                      "n_prev": before.get(k, 0) if has_prev else None,
                      "growth": round((len(cids) + 1) / (before.get(k, 0) + 1), 2) if has_prev else None})
    items.sort(key=lambda x: ((x["growth"] or 0), x["n_clusters"]) if has_prev else x["n_clusters"],
               reverse=True)
    return {"has_prev": has_prev, "items": items[: cfg["max_items"]]}


# a product type or a description, not a product's name ('fragrance mists' from a list of
# picks, '샤넬 | 새 향수'): the row tells the reader nothing, so it is left out
GENERIC_PRODUCT = re.compile(r"(?:새|신규)?\s?(?:향수|신제품|제품|마스크팩|립스틱|립밤|샴푸|헤어팩|토닉|토너|"
                             r"컨실러|선크림|에센스|세럼|크림|앰플|쿠션)")


def generic_product(name: str) -> bool:
    n = (name or "").strip()
    if re.fullmatch(r"[ -~]+", n) and not re.search(r"[A-Z]", n):
        return True    # all-lowercase English: 'colour cosmetics', 'three new fragrances'
    return bool(GENERIC_PRODUCT.fullmatch(n))


def launches(clusters: list[Cluster], ym: str, ents: Entities, until=None) -> list[dict]:
    """Products launched in the window, with a verbatim quote saying so.

    date_basis "article": the article states the launch date.
    date_basis "published": the article reports the launch as done ("출시했다")
    without a date → the article's publish date stands in (marked in the report).
    """
    first, last = month_bounds(ym)
    if until:
        last = min(last, until)
    out: list[dict] = []
    for c in clusters:
        for d in c.docs:
            for p in d["extraction"].get("products", []):
                ld, basis = p.get("launch_date"), "article"
                if not p.get("launch_quote") or generic_product(p["name"]):
                    continue
                if not (ld and _in_month(ld, first, last)):
                    pub = kst_date(d.get("published_at"))
                    if p.get("launch_status") != "launched" or ld or not (pub and first <= pub <= last):
                        continue
                    ld, basis = pub.isoformat(), "published"
                brand = ents.canon(p.get("brand") or "")
                dup = next((x for x in out if same_product(x, {"brand": brand, "name": p["name"]})), None)
                if dup:
                    if dup["date_basis"] == "published" and basis == "article":
                        out.remove(dup)   # a stated date beats the publish-date stand-in
                    else:
                        continue
                out.append({"brand": brand, "name": p["name"], "launch_date": ld, "date_basis": basis,
                            "category": d["extraction"].get("category"), "group": d["group"],
                            "n_sources": len(c.sources),
                            "notes": p.get("notes", []), "doc_id": d["doc_id"],
                            "quote": p["launch_quote"], "url": d["url"],
                            "source_name": d["source_name"],
                            "press_release": c.press_release, "lang": d["lang"]})
    return sorted(out, key=lambda x: x["launch_date"])


TRADE_GROUPS = {"kr_trade", "global_trade"}
CATEGORY_KO = {"skincare": "스킨케어", "makeup": "메이크업", "hair": "헤어", "body": "바디",
               "ingredient": "원료", "fragrance": "향수"}


def launch_groups(items: list[dict], other_max: int) -> dict:
    """Deck view of launches: every fragrance launch, then the other launches
    ranked by trade-press coverage (trade press first, more outlets first)."""
    frag = [x for x in items if x.get("category") == "fragrance"]
    rest = [x for x in items if x.get("category") != "fragrance"]
    ranked = sorted(rest, key=lambda x: (x.get("group") in TRADE_GROUPS, x.get("n_sources", 1)), reverse=True)
    shown = sorted(ranked[:other_max], key=lambda x: x["launch_date"])
    cats = Counter(CATEGORY_KO.get(x.get("category"), "기타") for x in rest).most_common()
    return {"fragrance": frag, "other": shown, "other_total": len(rest),
            "by_category_text": ", ".join(f"{k} {n}개" for k, n in cats)}


def _in_month(ld: str, first, last) -> bool:
    if re.fullmatch(r"\d{4}-\d{2}", ld):
        return ld == f"{first.year:04d}-{first.month:02d}"
    try:
        from datetime import date
        d = date.fromisoformat(ld)
    except ValueError:
        return False
    return first <= d <= last


def same_product(a: dict, b: dict) -> bool:
    """Same brand and one name contains the other or the names are near-identical."""
    if _nospace(a["brand"] or "") != _nospace(b["brand"] or ""):
        return False
    na, nb = _nospace(a["name"]), _nospace(b["name"])
    return na in nb or nb in na or similar(na, nb, 0.6)


def product_claims(rec: dict, ents: Entities) -> dict[str, list[dict]]:
    """Notes and launch claims of one article, shaped like the rows of notes()/launches(),
    so the daily product check and the monthly report share verdicts."""
    out: dict[str, list[dict]] = {"notes": [], "launch": []}
    for p in rec["extraction"].get("products", []):
        if generic_product(p["name"]):
            continue
        brand = ents.canon(p.get("brand") or "")
        if p.get("notes") and p.get("notes_quote"):
            out["notes"].append({"brand": brand, "name": p["name"], "notes": p["notes"],
                                 "quote": p["notes_quote"], "doc_id": rec["doc_id"]})
        if p.get("launch_quote") and (p.get("launch_date") or p.get("launch_status") == "launched"):
            out["launch"].append({"brand": brand, "name": p["name"], "quote": p["launch_quote"],
                                  "doc_id": rec["doc_id"]})
    return out


def notes(clusters: list[Cluster], ents: Entities) -> dict:
    """Products whose notes are explicitly stated (quote-verified in enrich).

    Near-duplicate products are listed once, with the first article's notes and quote
    (notes from another article would otherwise be cited to the wrong source).
    """
    items: list[dict] = []
    for c in clusters:
        for d in c.docs:
            for p in d["extraction"].get("products", []):
                if p.get("notes") and p.get("notes_quote") and not generic_product(p["name"]):
                    cand = {"brand": ents.canon(p.get("brand") or ""), "name": p["name"]}
                    dup = next((it for it in items if same_product(it, cand)), None)
                    if dup:
                        continue
                    items.append({"brand": ents.canon(p.get("brand") or ""), "name": p["name"],
                                  "notes": p["notes"], "quote": p["notes_quote"],
                                  "doc_id": d["doc_id"], "url": d["url"],
                                  "source_name": d["source_name"]})
    return notes_block(items)


def notes_block(items: list[dict]) -> dict:
    freq = Counter(_kw(n) for it in items for n in set(it["notes"]))
    return {"n": len(items), "items": items, "note_freq": freq.most_common(15)}


def _cluster_card(c: Cluster) -> dict:
    r = c.rep
    ex = r["extraction"]
    return {"cid": c.cid, "doc_id": r["doc_id"], "title": r["title"], "url": r["url"],
            "source_name": r["source_name"], "lang": r["lang"], "group": r["group"],
            "published": (r.get("published_at") or "")[:10],
            "evidence_grade": r.get("evidence_grade"),
            "key_fact": ex.get("key_fact"), "quote": ex.get("key_fact_quote"),
            "category": ex.get("category"), "event_type": ex.get("event_type"),
            "n_docs": len(c.docs), "n_sources": len(c.sources),
            "press_release": c.press_release, "doc_ids": [d["doc_id"] for d in c.docs]}


def market(clusters: list[Cluster], limit: int = 12) -> dict:
    """Clusters about business/market, ranked by coverage breadth."""
    cards = [_cluster_card(c) for c in clusters
             if (c.rep["group"] in ("kr_trade", "kr_news", "global_trade")
                 or c.rep.get("source") in PRESS_BOARDS)
             and c.rep["extraction"].get("event_type") in MARKET_EVENTS
             and c.rep["extraction"].get("key_fact")]
    cards.sort(key=lambda x: (x["n_sources"], x["n_docs"], not x["press_release"]), reverse=True)
    return {"kr": [x for x in cards if x["lang"] == "ko"][:limit],
            "global": [x for x in cards if x["lang"] != "ko"][:limit]}


# Press-release boards mix regulation with other news (export figures, events).
PRESS_BOARDS = {"mfds_press"}


def regulation(clusters: list[Cluster], official: list[str]) -> dict:
    """Official notices only (authorities in `official`); competitor news is not reported.

    Notice/law boards are regulation by nature; a press release counts only when
    enrich classified it as regulation (others may go to the market section).
    """
    reg = [_cluster_card(c) for c in clusters
           if c.rep["group"] == "regulation" and c.rep.get("source") in official
           and (c.rep.get("source") not in PRESS_BOARDS
                or c.rep["extraction"].get("event_type") == "regulation")]
    return {"regulation": sorted(reg, key=lambda x: x["published"]), "competitors": []}


def shopping_block(cfg: dict, ym: str, until=None) -> dict:
    """Weekly NAVER Shopping click trend for fixed scented-product terms (one request, one scale)."""
    terms = cfg.get("shopping_terms") or []
    if not terms:
        return {}
    try:
        return datalab.shopping_keywords(terms, cfg["shopping_category"], ym, cfg["datalab_months"], until)
    except RuntimeError as e:
        log.warning("datalab shopping keywords failed: %s", e)
        return {"error": str(e)}


def datalab_block(terms: list[str], ym: str, cfg: dict, until=None) -> dict:
    out = {}
    try:
        out["search"] = datalab.search_trend(terms, cfg["anchor_keyword"], ym, cfg["datalab_months"],
                                             until)
    except RuntimeError as e:
        log.warning("datalab search failed: %s", e)
        out["search_error"] = str(e)
    try:
        out["shopping"] = datalab.shopping_category(cfg["shopping_category"], "화장품/미용", ym,
                                                    cfg["datalab_months"], until)
    except RuntimeError as e:
        log.warning("datalab shopping failed: %s", e)
        out["shopping_error"] = str(e)
    return out


# Store promotions are not industry events for a sales calendar.
PROMO = re.compile(r"할인|프로모션|세일|기획전|특가|이벤트|광군절|블랙프라이데이|DAY|데이|위크|증정|판촉|"
                   r"주주총회|사전 행사|인증식|수여식|"
                   # store openings ('올리브베러 성수점') and in-house gatherings are not industry dates
                   r"[가-힣](?:점|매장)$|개점|그랜드\s?오픈|플래그십|flagship|오리엔테이션|파티|발대식", re.I)
# English names of the same gathering ('in-cosmetics Asia' = '인-코스메틱스 아시아')
EVENT_WORDS = (("incosmetics", "인코스메틱스"), ("cosmoprof", "코스모프로프"), ("beautyworld", "뷰티월드"),
               ("hongkong", "홍콩"), ("asia", "아시아"), ("beauty", "뷰티"), ("expo", "엑스포"),
               ("fair", "페어"), ("show", "쇼"))


def _event_key(name: str) -> str:
    """'2026 K-뷰티 엑스포(K-BEAUTY EXPO)' and 'K-뷰티엑스포 코리아' → comparable core."""
    s = re.sub(r"\(.*?\)|\d+|코리아|korea|제\s*\d+\s*회", "", name, flags=re.I).lower()
    s = re.sub(r"[^가-힣a-z]", "", s)
    for en, ko in EVENT_WORDS:
        s = s.replace(en, ko)
    return s


# Industry gatherings; other events stay only when two or more articles report them.
INDUSTRY_EVENT = re.compile(r"엑스포|박람회|전시|페어|어워드|awards?|시상|expo|show|fair|설명회|세미나|"
                            r"컨퍼런스|콘퍼런스|포럼|교육|과정|상담회|키메스|코스모|뷰티\s?월드|beautyworld|summit", re.I)


def upcoming_events(clusters: list[Cluster], after, days: int = 60, limit: int = 20) -> list[dict]:
    """Industry events dated in articles that start on or after `after`, within `days`.

    Dates and quotes were checked in enrich (verbatim quote holding the start day).
    Store promotions are left out; one event reported by several outlets is listed
    once (names compared without year, brackets and spacing).
    """
    from datetime import date, timedelta
    horizon = after + timedelta(days=days)
    out: list[dict] = []
    for c in clusters:
        for d in c.docs:
            for e in d["extraction"].get("events", []):
                start = date.fromisoformat(e["start_date"])
                end = date.fromisoformat(e["end_date"]) if e.get("end_date") else start
                if start < after or start > horizon or PROMO.search(e["name"]):
                    continue
                k = _event_key(e["name"])
                dup = next((x for x in out if x["start"] == start.isoformat() and k and x["key"]
                            and (k in x["key"] or x["key"] in k or similar(k, x["key"], 0.5))), None)
                if dup:
                    dup["n_docs"] += 1
                    # the report is Korean: name the event as a Korean outlet writes it
                    if not re.search(r"[가-힣]", dup["name"]) and re.search(r"[가-힣]", e["name"]):
                        dup.update(name=e["name"], place=e.get("place"), quote=e["quote"], doc_id=d["doc_id"])
                    continue
                out.append({"name": e["name"], "key": k, "start": start.isoformat(),
                            "end": end.isoformat() if end != start else None,
                            "place": e.get("place"), "quote": e["quote"], "doc_id": d["doc_id"],
                            "n_docs": 1})
    out = [x for x in out if x["n_docs"] >= 2 or INDUSTRY_EVENT.search(x["name"])]
    out.sort(key=lambda x: (x["start"], -x["n_docs"]))
    return out[:limit]


def _ingredient_key(name: str) -> str:
    """'그로우키(GROWKEY™)' and '그로우키' are one ingredient; spacing and case ignored."""
    return _nospace(re.sub(r"\(.*?\)|[™®]", "", name))


def ingredients(clusters: list[Cluster], min_clusters: int = 2, limit: int = 10) -> dict:
    """Ingredients named in articles, ranked by how many distinct news items name them."""
    seen: dict[str, set] = defaultdict(set)
    label: dict[str, Counter] = defaultdict(Counter)
    reps: dict[str, list] = defaultdict(list)
    for c in clusters:
        for d in c.docs:
            for g in d["extraction"].get("ingredients", []):
                k = _ingredient_key(g["name"])
                if not k:
                    continue
                label[k][re.sub(r"\(.*?\)|[™®]", "", g["name"]).strip()] += 1
                if c.cid not in seen[k]:
                    seen[k].add(c.cid)
                    reps[k].append({"doc_id": d["doc_id"], "title": d["title"],
                                    "named": k in _nospace(d["title"])})
    # representative articles: ones that name the ingredient in the title first
    items = [{"name": label[k].most_common(1)[0][0], "n": len(v),
              "reps": sorted(reps[k], key=lambda r: not r["named"])[:2]}
             for k, v in seen.items() if len(v) >= min_clusters]
    items.sort(key=lambda x: x["n"], reverse=True)
    return {"items": items[:limit], "n_named": len(seen)}


def run(clusters: list[Cluster], prev: list[Cluster], ym: str, until=None) -> dict:
    cfg = load("report")
    ents = Entities()
    kw = keywords(clusters, prev, cfg["sections"]["keywords"], cfg.get("keyword_stoplist"))
    return {
        "month": ym,
        "counts": {"clusters": len(clusters), "docs": sum(len(c.docs) for c in clusters)},
        "keywords": kw,
        "datalab": datalab_block([k["term"] for k in kw["items"]], ym, cfg, until) if kw["items"] else {},
        "launches": launches(clusters, ym, ents, until),
        "notes": notes(clusters, ents),
        "market": market(clusters),
        "regulation": regulation(clusters, cfg.get("regulation_sources", [])),
        "calendar": cfg.get("regulation_calendar", []),
        "events": upcoming_events(clusters, until or month_bounds(ym)[1],
                                  cfg["sections"]["events"].get("days", 60)),
        "ingredients": ingredients(clusters, cfg["sections"]["ingredients"].get("min_clusters", 2)),
        "shopping_terms": shopping_block(cfg, ym, until),
    }
