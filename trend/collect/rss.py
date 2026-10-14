"""RSS 2.0 / Atom collector."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from .. import store
from ..http import Client
from ..util import clean_text, doc_id, parse_date, to_kst_iso, utcnow_iso
from . import Result
from .article import extract_body

log = logging.getLogger(__name__)
NS = {"atom": "http://www.w3.org/2005/Atom",
      "content": "http://purl.org/rss/1.0/modules/content/",
      "dc": "http://purl.org/dc/elements/1.1/"}


def _text(el, *paths) -> str | None:
    for p in paths:
        x = el.find(p, NS)
        if x is not None:
            v = x.text or x.get("href")
            if v and v.strip():
                return v.strip()
    return None


def parse_feed(body: bytes) -> list[dict]:
    root = ET.fromstring(body)
    items = root.findall(".//item") or root.findall(".//atom:entry", NS)
    out = []
    for it in items:
        out.append({
            "title": clean_text(_text(it, "title", "atom:title")),
            "link": _text(it, "link", "atom:link"),
            "summary": clean_text(_text(it, "description", "atom:summary")),
            "content": clean_text(_text(it, "content:encoded", "atom:content")),
            "date": _text(it, "pubDate", "dc:date", "atom:published", "atom:updated"),
            "author": clean_text(_text(it, "author", "dc:creator", "atom:author/atom:name")),
        })
    return out


def collect(src: dict, client: Client, known: set[str]) -> Result:
    r = client.request(src["url"], headers={"Accept": "application/rss+xml, application/xml, */*"})
    if not r.ok:
        return Result(src["id"], False, error=r.error or f"HTTP {r.status}")
    try:
        items = parse_feed(r.body)
    except ET.ParseError as e:
        return Result(src["id"], False, error=f"parse: {e}")
    items = items[: src.get("max_items", len(items))]
    keep = src.get("title_filter")
    docs, skipped_robots = [], 0
    for it in items:
        if not it["link"] or not it["title"]:
            continue
        if keep and not any(k in it["title"] for k in keep):
            continue
        did = doc_id(it["link"])
        body = it["content"] if len(it["content"]) > 300 else None
        if body is None and src.get("fetch_body") and did not in known:
            if client.allowed(it["link"]):
                ar = client.request(it["link"], headers={"Accept": "text/html"})
                body = extract_body(ar.text) if ar.ok else None
            else:
                skipped_robots += 1
        if body:
            store.save_body(did, body)
        published = parse_date(it["date"], src.get("naive_tz", "UTC"))
        docs.append({
            "doc_id": did, "source": src["id"], "source_name": src["name"],
            "group": src["group"], "lang": src.get("lang", "en"),
            "url": it["link"], "title": it["title"],
            "summary": it["summary"][:600],
            "published_at": to_kst_iso(published),
            "date_source": "feed" if published else "missing",
            "fetched_at": utcnow_iso(), "author": it["author"] or None,
            "evidence_grade": src.get("evidence_grade", "article"),
            "body_chars": len(body) if body else 0,
        })
    note = f"robots skipped {skipped_robots}" if skipped_robots else None
    return Result(src["id"], True, docs, note=note)
