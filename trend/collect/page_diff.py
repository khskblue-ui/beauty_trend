"""List pages without a feed: detect new article links against stored state."""
from __future__ import annotations

import re
import urllib.parse

from .. import store
from ..http import Client
from ..util import clean_text, doc_id, parse_date, to_kst_iso, utcnow_iso
from . import Result

DATE_RE = re.compile(
    r"\b(\d{1,2} (?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December) 20\d\d)\b")


BLOCK_RE = re.compile(r"<(article|li)\b[^>]*>(.*?)</\1>", re.S | re.I)
HEAD_RE = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.S | re.I)


def extract_links(html: str, base: str, pattern: str) -> list[dict]:
    """Article links matching pattern, with title/date/summary from the enclosing card.

    Cards are <article>/<li> blocks; title = first heading (else longest anchor
    text), date = first date in the card text, summary = remaining card text.
    """
    out: dict[str, dict] = {}
    blocks = [m.group(2) for m in BLOCK_RE.finditer(html)] or [html]
    for block in blocks:
        for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I):
            url = urllib.parse.urljoin(base, m.group(1))
            if not re.search(pattern, url):
                continue
            head = HEAD_RE.search(block)
            title = clean_text(head.group(1)) if head else clean_text(m.group(2))
            text = clean_text(block)
            d = DATE_RE.search(text)
            summary = text.replace(title, "", 1)
            if d:
                summary = summary.replace(d.group(1), "", 1)
            summary = re.sub(r"\b(Read more|News|Press release)\b", " ", summary)
            cur = out.get(url)
            if cur is None or len(title) > len(cur["title"]):
                out[url] = {"url": url, "title": title, "date": d.group(1) if d else None,
                            "summary": re.sub(r"\s+", " ", summary).strip()[:400]}
    return [x for x in out.values() if len(x["title"]) >= 8]


def collect(src: dict, client: Client) -> Result:
    if not client.allowed(src["url"]):
        return Result(src["id"], False, error="robots disallow")
    r = client.request(src["url"], headers={"Accept": "text/html"})
    if not r.ok:
        return Result(src["id"], False, error=r.error or f"HTTP {r.status}")
    links = extract_links(r.text, src["url"], src["link_pattern"])
    if not links:  # layout changed → health check should flag this
        return Result(src["id"], False, error="no links matched pattern")
    state_path = f"state/page_diff_{src['id']}.json"
    seen = set(store.read_json(store.data_dir() / state_path, []) or [])
    docs = []
    for ln in links:
        if ln["url"] in seen:
            continue
        published = parse_date(ln["date"]) if ln["date"] else None
        docs.append({
            "doc_id": doc_id(ln["url"]), "source": src["id"], "source_name": src["name"],
            "group": src["group"], "lang": "en", "url": ln["url"], "title": ln["title"],
            "summary": ln["summary"], "published_at": to_kst_iso(published),
            "date_source": "page" if published else "first_seen",
            "fetched_at": utcnow_iso(), "evidence_grade": "headline", "body_chars": 0,
        })
    store.write_json(state_path, sorted(seen | {ln["url"] for ln in links}))
    return Result(src["id"], True, docs, note=f"{len(links)} links on page")
