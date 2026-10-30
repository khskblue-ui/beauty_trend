"""Daily collection: every configured source, new docs only, plus a health record."""
from __future__ import annotations

import logging
from datetime import date

from .. import store
from ..config import load
from ..http import Client
from ..util import kst_date, now_kst, url_key, utcnow_iso
from . import Result, backfill, cellar, fedreg, naver_news, page_diff, rss

log = logging.getLogger(__name__)


def run(only: set[str] | None = None, naver_pages: int = 1,
        since: date | None = None, backfill_since: date | None = None) -> dict:
    cfg = load("sources")
    client = Client()
    known = store.known_ids()
    known_urls = {url_key(d["url"]) for d in store.iter_raw() if d.get("url")}
    results: list[Result] = []

    def want(sid: str) -> bool:
        return only is None or sid in only

    for src in cfg.get("rss", []):
        if want(src["id"]):
            results.append(rss.collect(src, client, known))
    for src in cfg.get("page_diff", []):
        if want(src["id"]):
            results.append(page_diff.collect(src, client))
    for src in cfg.get("cellar", []):
        if want(src["id"]):
            results.append(cellar.collect(src, client))
    for src in cfg.get("fedreg", []):
        if want(src["id"]):
            results.append(fedreg.collect(src, client, since=since))
    if backfill_since:
        # archive pages for days the feeds no longer hold (see collect/backfill.py)
        dates = {d["doc_id"]: kst_date(d.get("published_at")) for d in store.iter_raw()}
        for src in cfg.get("rss", []):
            if want(src["id"]) and src.get("archive"):
                res = backfill.collect(src, client, backfill_since, now_kst().date(), dates)
                res.source = src["id"]
                results.append(res)
    if want("naver_news"):
        results.append(naver_news.collect(cfg["naver_news"], client, pages=naver_pages, since=since))

    day = now_kst().date().isoformat()
    # a second run on the same day (Actions for MFDS, the work session for the rest) adds to
    # the day's record instead of replacing it
    prev = store.read_json(store.data_dir() / "health" / f"{day}.json", {}) or {}
    health = {"day": day, "finished_at": utcnow_iso(), "sources": dict(prev.get("sources", {}))}
    for res in results:
        # same article under another id (http vs https, www): skip it too
        new = [d for d in res.docs if d["doc_id"] not in known and url_key(d["url"]) not in known_urls]
        known.update(d["doc_id"] for d in new)
        known_urls.update(url_key(d["url"]) for d in new)
        n = store.append_docs(day, res.source, new) if new else 0
        key = res.source if res.source not in health["sources"] else res.source + "+backfill"
        health["sources"][key] = {"ok": res.ok, "seen": len(res.docs), "new": n,
                                         "error": res.error, "note": res.note}
        log.info("%-20s ok=%s seen=%d new=%d %s", res.source, res.ok, len(res.docs), n,
                 res.error or res.note or "")
    store.write_json(f"health/{day}.json", health)
    return health
