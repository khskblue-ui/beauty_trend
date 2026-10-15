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
    return re.sub(r"\s+", " ", s).strip().lower()


def _nospace(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


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
                if not p.get("launch_quote"):
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
               "retail": "유통", "ingredient": "원료", "fragrance": "향수"}


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


def notes(clusters: list[Cluster], ents: Entities) -> dict:
    """Products whose notes are explicitly stated (quote-verified in enrich).

    Near-duplicate products are merged; the merged entry keeps the union of notes.
    """
    items: list[dict] = []
    for c in clusters:
        for d in c.docs:
            for p in d["extraction"].get("products", []):
                if p.get("notes") and p.get("notes_quote"):
                    cand = {"brand": ents.canon(p.get("brand") or ""), "name": p["name"]}
                    dup = next((it for it in items if same_product(it, cand)), None)
                    if dup:
                        dup["notes"] += [n for n in p["notes"] if n not in dup["notes"]]
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
    }
