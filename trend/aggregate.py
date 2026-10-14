"""aggregate: every number in the report is computed here, never by the LLM."""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from . import datalab
from .config import load
from .normalize import Cluster, Entities
from .util import kst_date, month_bounds

log = logging.getLogger(__name__)
MARKET_EVENTS = {"business", "market_trend", "retail", "event", "ingredient"}


def _kw(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def keywords(clusters: list[Cluster], prev: list[Cluster], cfg: dict) -> dict:
    """Terms ranked by distinct-cluster count (growth vs previous month if available)."""
    cur, before = defaultdict(set), Counter()
    label: dict[str, Counter] = defaultdict(Counter)
    for c in clusters:
        for d in c.docs:
            for k in d["extraction"].get("keywords", []):
                cur[_kw(k)].add(c.cid)
                label[_kw(k)][k.strip()] += 1
    for c in prev:
        for k in {_kw(k) for d in c.docs for k in d["extraction"].get("keywords", [])}:
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


def launches(clusters: list[Cluster], ym: str, ents: Entities) -> list[dict]:
    first, last = month_bounds(ym)
    out, seen = [], set()
    for c in clusters:
        for d in c.docs:
            for p in d["extraction"].get("products", []):
                ld = p.get("launch_date")
                if not ld or not p.get("launch_quote"):
                    continue
                if not _in_month(ld, first, last):
                    continue
                brand = ents.canon(p.get("brand") or "")
                key = (brand.lower(), _kw(p["name"]))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"brand": brand, "name": p["name"], "launch_date": ld,
                            "notes": p.get("notes", []), "doc_id": d["doc_id"],
                            "quote": p["launch_quote"], "url": d["url"],
                            "source_name": d["source_name"],
                            "press_release": c.press_release, "lang": d["lang"]})
    return sorted(out, key=lambda x: x["launch_date"])


def _in_month(ld: str, first, last) -> bool:
    if re.fullmatch(r"\d{4}-\d{2}", ld):
        return ld == f"{first.year:04d}-{first.month:02d}"
    try:
        from datetime import date
        d = date.fromisoformat(ld)
    except ValueError:
        return False
    return first <= d <= last


def notes(clusters: list[Cluster], ents: Entities) -> dict:
    """Products whose notes are explicitly stated (quote-verified in enrich)."""
    items, seen = [], set()
    for c in clusters:
        for d in c.docs:
            for p in d["extraction"].get("products", []):
                if p.get("notes") and p.get("notes_quote"):
                    key = _kw(p["name"])
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append({"brand": ents.canon(p.get("brand") or ""), "name": p["name"],
                                  "notes": p["notes"], "quote": p["notes_quote"],
                                  "doc_id": d["doc_id"], "url": d["url"],
                                  "source_name": d["source_name"]})
    freq = Counter(_kw(n) for it in items for n in it["notes"])
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
             if c.rep["group"] in ("kr_trade", "kr_news", "global_trade")
             and c.rep["extraction"].get("event_type") in MARKET_EVENTS
             and c.rep["extraction"].get("key_fact")]
    cards.sort(key=lambda x: (x["n_sources"], x["n_docs"], not x["press_release"]), reverse=True)
    return {"kr": [x for x in cards if x["lang"] == "ko"][:limit],
            "global": [x for x in cards if x["lang"] != "ko"][:limit]}


def regulation(clusters: list[Cluster]) -> dict:
    reg = [_cluster_card(c) for c in clusters if c.rep["group"] == "regulation"]
    comp = [_cluster_card(c) for c in clusters if c.rep["group"] == "competitor"]
    return {"regulation": sorted(reg, key=lambda x: x["published"]),
            "competitors": sorted(comp, key=lambda x: x["published"])}


def datalab_block(terms: list[str], ym: str, cfg: dict) -> dict:
    out = {}
    try:
        out["search"] = datalab.search_trend(terms, cfg["anchor_keyword"], ym, cfg["datalab_months"])
    except RuntimeError as e:
        log.warning("datalab search failed: %s", e)
        out["search_error"] = str(e)
    try:
        out["shopping"] = datalab.shopping_category(cfg["shopping_category"], "화장품/미용", ym,
                                                    cfg["datalab_months"])
    except RuntimeError as e:
        log.warning("datalab shopping failed: %s", e)
        out["shopping_error"] = str(e)
    return out


def run(clusters: list[Cluster], prev: list[Cluster], ym: str) -> dict:
    cfg = load("report")
    ents = Entities()
    kw = keywords(clusters, prev, cfg["sections"]["keywords"])
    return {
        "month": ym,
        "counts": {"clusters": len(clusters), "docs": sum(len(c.docs) for c in clusters)},
        "keywords": kw,
        "datalab": datalab_block([k["term"] for k in kw["items"]], ym, cfg) if kw["items"] else {},
        "launches": launches(clusters, ym, ents),
        "notes": notes(clusters, ents),
        "market": market(clusters),
        "regulation": regulation(clusters),
        "calendar": cfg.get("regulation_calendar", []),
    }
