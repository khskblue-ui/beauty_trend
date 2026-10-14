"""NAVER API HUB news search (general press; trade press comes via RSS)."""
from __future__ import annotations

import os
import urllib.parse

from ..http import Client
from ..util import clean_text, doc_id, parse_date, to_kst_iso, utcnow_iso
from . import Result

HOST = "https://naverapihub.apigw.ntruss.com"


def auth_headers() -> dict:
    """Attach keys only when present (GitHub Actions). Otherwise a proxy may inject them."""
    cid, sec = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if cid and sec:
        return {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec}
    return {}


def search(client: Client, query: str, display: int = 100, start: int = 1) -> dict | None:
    q = urllib.parse.urlencode({"query": query, "display": display, "start": start, "sort": "date"})
    r = client.request(f"{HOST}/search/v1/news?{q}", headers=auth_headers())
    if not r.ok:
        raise RuntimeError(r.error or f"HTTP {r.status}: {r.text[:200]}")
    return r.json()  # Content-Type is text/plain; parse regardless


def relevant(title: str, summary: str, cfg: dict) -> bool:
    return (any(k in title for k in cfg["title_any"])
            and not any(k in f"{title} {summary}" for k in cfg["exclude_any"]))


def to_doc(item: dict, query: str, group: str) -> dict:
    url = item.get("originallink") or item["link"]
    return {
        "doc_id": doc_id(url), "source": "naver_news", "source_name": "네이버 뉴스 검색",
        "group": group, "lang": "ko", "url": url, "naver_link": item.get("link"),
        "title": clean_text(item["title"]), "summary": clean_text(item["description"]),
        "published_at": to_kst_iso(parse_date(item.get("pubDate"))),
        "date_source": "api", "fetched_at": utcnow_iso(), "query": query,
        "evidence_grade": "article", "body_chars": 0,
    }


def collect(cfg: dict, client: Client, pages: int = 1, since=None) -> Result:
    """pages>1 walks back (start=1,101,...) for backfill; stops once older than `since`."""
    docs, errors = {}, []
    for q in cfg["queries"]:
        for p in range(pages):
            try:
                d = search(client, q, cfg.get("display", 100), 1 + p * 100)
            except RuntimeError as e:
                errors.append(f"{q}: {e}")
                break
            items = d.get("items", [])
            for it in items:
                doc = to_doc(it, q, cfg["group"])
                if relevant(doc["title"], doc["summary"], cfg):
                    docs.setdefault(doc["doc_id"], doc)
            oldest = parse_date(items[-1]["pubDate"]) if items else None
            if not items or len(items) < 100 or (since and oldest and oldest.date() < since):
                break
    ok = len(errors) < len(cfg["queries"])
    return Result("naver_news", ok, list(docs.values()), error="; ".join(errors) or None)
