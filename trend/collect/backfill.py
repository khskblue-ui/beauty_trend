"""Backfill: articles a feed no longer holds, from the source's own archive.

RSS feeds keep only the last few days, so a missed day (or a late start) loses
articles for good. Each source may declare an `archive` (sources.yaml):

  kind: list     article list pages; `url` has {page}; links matching `link_pattern`
  kind: feed     paged feed; `url` has {page}
  kind: sitemap  sitemap.xml; date = <lastmod> (only for sites whose articles carry no date)

Dates for `list` come from the article page (article:published_time / JSON-LD).
robots.txt is checked for every page; pacing is the shared Client's.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import date

from .. import store
from ..http import Client
from ..util import clean_text, doc_id, kst_date, parse_date, to_kst_iso, utcnow_iso
from . import Result
from .article import extract_body
from .rss import parse_feed

log = logging.getLogger(__name__)

META_DATE = [
    r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
    r'"datePublished"\s*:\s*"([^"]+)"',
]


def _meta(html: str, prop: str) -> str | None:
    m = (re.search(rf'<meta[^>]+(?:property|name)="{prop}"[^>]+content="([^"]*)"', html)
         or re.search(rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{prop}"', html))
    return clean_text(m.group(1)) if m else None


def page_date(html: str, tz: str) -> str | None:
    for pat in META_DATE:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _doc(src: dict, url: str, title: str, summary: str, published, date_source: str,
         body: str | None) -> dict:
    did = doc_id(url)
    if body:
        store.save_body(did, body)
    return {
        "doc_id": did, "source": src["id"], "source_name": src["name"],
        "group": src["group"], "lang": src.get("lang", "en"), "url": url,
        "title": title, "summary": (summary or "")[:600],
        "published_at": to_kst_iso(published), "date_source": date_source,
        "fetched_at": utcnow_iso(), "evidence_grade": src.get("evidence_grade", "article"),
        "body_chars": len(body) if body else 0, "collected_via": "backfill",
    }


def _article(src: dict, client: Client, url: str, published=None,
             date_source: str = "page") -> tuple[dict | None, date | None]:
    if not client.allowed(url):
        return None, None
    r = client.request(url, headers={"Accept": "text/html"})
    if not r.ok:
        return None, None
    html = r.text
    if published is None:
        published = parse_date(page_date(html, src.get("naive_tz", "UTC")), src.get("naive_tz", "UTC"))
    title = _meta(html, "og:title") or clean_text((re.search(r"<title>(.*?)</title>", html, re.S) or [None, ""])[1])
    summary = _meta(html, "og:description") or _meta(html, "description") or ""
    body = extract_body(html) if src.get("fetch_body") else None
    if not title or not published:
        return None, None
    return _doc(src, url, title, summary, published, date_source, body), kst_date(to_kst_iso(published))


def _in_range(d: date | None, since: date, until: date) -> bool:
    return d is not None and since <= d <= until


def collect(src: dict, client: Client, since: date, until: date,
            known: dict[str, date | None]) -> Result:
    """known: doc_id → KST publish date of docs already stored (skipped, but their
    dates still tell when the list has gone past the window)."""
    arc = src.get("archive")
    if not arc:
        return Result(src["id"], True, note="no archive configured")
    kind, docs = arc["kind"], []
    try:
        if kind == "feed":
            for page in range(1, arc.get("max_pages", 20) + 1):
                r = client.request(arc["url"].format(page=page))
                if not r.ok:
                    break
                items = parse_feed(r.body)
                if not items:
                    break
                for it in items:
                    pub = parse_date(it["date"], src.get("naive_tz", "UTC"))
                    if _in_range(kst_date(to_kst_iso(pub)), since, until):
                        url = urllib.parse.urljoin(arc["url"], it["link"])
                        docs.append(_doc(src, url, it["title"], it["summary"], pub, "feed", None))
                oldest = min((kst_date(to_kst_iso(parse_date(i["date"]))) for i in items
                              if i["date"]), default=None)
                if oldest and oldest < since:
                    break
        elif kind == "sitemap":
            r = client.request(arc["url"])
            if not r.ok:
                return Result(src["id"], False, error=f"sitemap HTTP {r.status}")
            for loc, lastmod in re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", r.text):
                d = date.fromisoformat(lastmod[:10])
                if not _in_range(d, since, until) or doc_id(loc) in known:
                    continue
                if not re.search(arc.get("link_pattern", "."), loc):
                    continue
                doc, _ = _article(src, client, loc, parse_date(lastmod, "UTC"), "sitemap_lastmod")
                if doc:
                    docs.append(doc)
        elif kind == "list":
            for page in range(arc.get("first_page", 1), arc.get("max_pages", 30) + 1):
                url = arc["url"].format(page=page, offset=(page - 1) * arc.get("step", 0))
                if not client.allowed(url):
                    return Result(src["id"], False, docs, error="robots disallow list page")
                r = client.request(url, headers={"Accept": "text/html"})
                if not r.ok:
                    break
                b = re.search(r'<base\s+href="([^"]+)"', r.text)   # SPIP pages set <base>
                base = urllib.parse.urljoin(url, b.group(1)) if b else url
                links = list(dict.fromkeys(urllib.parse.urljoin(base, h) for h in
                                           re.findall(r'href="([^"]+)"', r.text)
                                           if re.search(arc["link_pattern"], h)))
                if not links:
                    break
                dates = []
                for ln in links:
                    if doc_id(ln) in known:
                        dates.append(known[doc_id(ln)])
                        continue
                    doc, d = _article(src, client, ln)
                    dates.append(d)
                    if doc and _in_range(d, since, until):
                        docs.append(doc)
                # stop once a whole page of new links is older than the window
                seen_dates = [d for d in dates if d]
                if seen_dates and max(seen_dates) < since:
                    break
        else:
            return Result(src["id"], False, error=f"unknown archive kind {kind}")
    except Exception as e:  # noqa: BLE001 — collectors never raise
        log.warning("backfill %s: %s", src["id"], e)
        return Result(src["id"], False, docs, error=str(e))
    uniq = list({d["doc_id"]: d for d in docs}.values())
    return Result(src["id"], True, uniq, note=f"backfill {since}~{until}")
