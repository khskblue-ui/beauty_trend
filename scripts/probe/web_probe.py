"""Low-volume probe of web/RSS sources for the phase-0 audit.

For each source: robots.txt (fetched once, evaluated for our UA and '*'),
home page (looks for <link rel=alternate> feeds and JS-only shells), then each
configured feed URL (item count, date fields, whether full text is present).
At most ~4-5 requests per source.

Usage:
  python scripts/probe/web_probe.py                # all sources
  python scripts/probe/web_probe.py cosmorning ifra # subset by key
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(__file__))
from _http import UA, request, save  # noqa: E402
from sources import SOURCES  # noqa: E402

BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NS = {"atom": "http://www.w3.org/2005/Atom",
      "content": "http://purl.org/rss/1.0/modules/content/",
      "dc": "http://purl.org/dc/elements/1.1/"}
TAG_RE = re.compile(r"<[^>]+>")


def strip(s: str | None) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html.unescape(s or ""))).strip()


def robots(base: str, paths: list[str]) -> dict:
    r = request(urllib.parse.urljoin(base, "/robots.txt"),
                headers={"User-Agent": BROWSER_UA})
    out = {"status": r.status, "error": r.error, "bot_wall": bot_wall(r)}
    if r.status == 200 and "<html" not in r.text[:500].lower():
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        out["allowed"] = {p: {"probe_ua": rp.can_fetch(UA, urllib.parse.urljoin(base, p)),
                              "*": rp.can_fetch("*", urllib.parse.urljoin(base, p))}
                          for p in paths}
        out["crawl_delay"] = rp.crawl_delay("*")
        out["head"] = r.text[:800]
    elif r.status == 200:
        out["note"] = "robots.txt returned HTML (treated as no robots file)"
    return out


DATE_RE = re.compile(
    r"20\d\d[-./]\d\d[-./]\d\d|\d\d[./]\d\d[./]20\d\d|"
    r"\b(?:\d{1,2} )?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* "
    r"(?:\d{1,2}, )?20\d\d")


def bot_wall(r) -> str | None:
    """Name the anti-bot layer if the response is a challenge/block page."""
    h = {k.lower(): v for k, v in r.headers.items()}
    if h.get("cf-mitigated"):
        return f"cloudflare:{h['cf-mitigated']}"
    if h.get("x-amzn-waf-action"):
        return f"aws-waf:{h['x-amzn-waf-action']}"
    if re.search(r"Just a moment|Attention Required|you have been blocked|"
                 r"잠시만 기다려 주세요|Request unsuccessful", r.text[:5000], re.I):
        return "challenge-page"
    return None


def page(url: str) -> dict:
    """Status + visible-text fingerprint, for list pages watched by diffing."""
    r = request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
    t = r.text
    vis = strip(re.sub(r"<script.*?</script>|<style.*?</style>", " ", t,
                       flags=re.S | re.I))
    return {"url": url, "status": r.status, "error": r.error, "final_url": r.url,
            "bot_wall": bot_wall(r), "bytes": len(r.body),
            "visible_text_chars": len(vis),
            "sha256_visible": hashlib.sha256(vis.encode()).hexdigest()[:16],
            "dates_found": len(DATE_RE.findall(vis)),
            "first_dates": DATE_RE.findall(vis)[:3]}


PAYWALL_RE = re.compile(
    r'"isAccessibleForFree"\s*:\s*"?false|subscribe to (?:continue|read)|'
    r"subscriber[- ]only|premium content|paywall|log ?in to read|"
    r"유료회원|로그인 후 이용", re.I)


def article(url: str) -> dict:
    """Fetch one article page: body size and paywall markers."""
    r = request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
    t = r.text
    paras = [strip(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", t, re.S | re.I)]
    body = " ".join(p for p in paras if len(p) > 40)
    return {"url": url, "status": r.status, "bot_wall": bot_wall(r),
            "paragraph_text_chars": len(body),
            "paywall_markers": sorted({m.group(0)[:40] for m in PAYWALL_RE.finditer(t)})[:5],
            "is_accessible_for_free": (m.group(1) if (m := re.search(
                r'"isAccessibleForFree"\s*:\s*"?(\w+)', t)) else None)}


def home(url: str) -> dict:
    r = request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
    t = r.text
    feeds = re.findall(
        r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', t, re.I)
    hrefs = [urllib.parse.urljoin(r.url, m.group(1)) for f in feeds
             if (m := re.search(r'href=["\']([^"\']+)', f))]
    body_text = strip(re.sub(r"<script.*?</script>|<style.*?</style>", " ", t,
                             flags=re.S | re.I))
    return {"status": r.status, "error": r.error, "final_url": r.url,
            "bytes": len(r.body), "visible_text_chars": len(body_text),
            "script_tags": len(re.findall(r"<script", t, re.I)),
            "feed_links": hrefs[:10],
            "bot_wall": bot_wall(r),
            "title": strip((re.search(r"<title>(.*?)</title>", t, re.S | re.I)
                            or [None, ""])[1])[:120]}


def feed(url: str) -> dict:
    r = request(url, headers={"User-Agent": BROWSER_UA,
                              "Accept": "application/rss+xml, application/xml, */*"})
    out = {"url": url, "status": r.status, "error": r.error, "bot_wall": bot_wall(r),
           "content_type": r.headers.get("Content-Type"), "bytes": len(r.body)}
    if r.status != 200:
        out["body_head"] = r.text[:200]
        return out
    try:
        root = ET.fromstring(r.body)
    except ET.ParseError as e:
        out["parse_error"] = str(e)
        out["body_head"] = r.text[:200]
        return out
    items = root.findall(".//item") or root.findall(".//atom:entry", NS)
    out["format"] = "atom" if root.tag.endswith("feed") else root.tag
    out["items"] = len(items)
    if not items:
        return out
    it = items[0]

    def g(*paths):
        for p in paths:
            el = it.find(p, NS)
            if el is not None and (el.text or el.get("href")):
                return el.text or el.get("href")
        return None

    desc = g("description", "atom:summary")
    content = g("content:encoded", "atom:content")
    out["first_item"] = {
        "title": strip(g("title", "atom:title"))[:120],
        "link": g("link", "atom:link"),
        "date_fields": {k: v for k in ("pubDate", "dc:date", "atom:published",
                                       "atom:updated")
                        if (v := g(k))},
        "description_chars": len(strip(desc)),
        "content_encoded_chars": len(strip(content)),
        "author": g("author", "dc:creator", "atom:author/atom:name"),
    }
    dates = [(i.findtext("pubDate") or i.findtext("dc:date", namespaces=NS)
              or i.findtext("atom:published", namespaces=NS)
              or i.findtext("atom:updated", namespaces=NS)) for i in items]
    dates = [d for d in dates if d]
    out["date_range"] = [dates[-1], dates[0]] if dates else None
    out["avg_description_chars"] = round(sum(
        len(strip(i.findtext("description") or
                  i.findtext("atom:summary", namespaces=NS))) for i in items) / len(items))
    return out


def probe(key: str, src: dict) -> dict:
    print(f"== {key}: {src['name']}")
    res = {"key": key, "name": src["name"], "base": src["base"]}
    res["robots"] = robots(src["base"], src.get("check_paths", ["/"]))
    time.sleep(1)
    if src.get("home", True):
        res["home"] = home(src.get("home_url", src["base"]))
        time.sleep(1)
    res["feeds"] = []
    for f in src.get("feeds", []):
        res["feeds"].append(feed(f))
        time.sleep(1)
    first = next((f["first_item"]["link"] for f in res["feeds"]
                  if (f.get("first_item") or {}).get("link")), None)
    if src.get("check_article", True) and first:
        res["article"] = article(urllib.parse.urljoin(src["base"], first.strip()))
        time.sleep(1)
    res["pages"] = []
    for p in src.get("pages", []):
        res["pages"].append(page(p))
        time.sleep(1)
    for k in ("robots", "home"):
        v = res.get(k) or {}
        print(f"   {k}: {v.get('status')} {v.get('error') or ''} {v.get('bot_wall') or ''} "
              f"{v.get('allowed') or v.get('feed_links') or ''}")
    for f in res["feeds"]:
        print(f"   feed {f['status']} items={f.get('items')} "
              f"{(f.get('first_item') or {}).get('date_fields')} "
              f"desc={f.get('avg_description_chars')} "
              f"content={(f.get('first_item') or {}).get('content_encoded_chars')} "
              f"{f.get('error') or f.get('parse_error') or ''} {f.get('bot_wall') or ''} {f['url']}")
    if res.get("article"):
        a = res["article"]
        print(f"   article {a['status']} body={a['paragraph_text_chars']} "
              f"free={a['is_accessible_for_free']} {a['paywall_markers']} {a['bot_wall'] or ''}")
    for p in res["pages"]:
        print(f"   page {p['status']} text={p['visible_text_chars']} dates={p['dates_found']} "
              f"{p['first_dates']} {p.get('bot_wall') or ''} {p.get('error') or ''} {p['url']}")
    return res


def main():
    keys = sys.argv[1:] or list(SOURCES)
    for k in keys:  # one file per source so a partial re-run merges cleanly
        print("   saved:", save(f"web/{k}.json", probe(k, SOURCES[k])))


if __name__ == "__main__":
    main()
