"""Daily collection: every configured source, new docs only, plus a health record."""
from __future__ import annotations

import logging
from datetime import date

from .. import store
from ..config import load
from ..http import Client
from ..util import now_kst, utcnow_iso
from . import Result, cellar, fedreg, naver_news, page_diff, rss

log = logging.getLogger(__name__)


def run(only: set[str] | None = None, naver_pages: int = 1,
        since: date | None = None) -> dict:
    cfg = load("sources")
    client = Client()
    known = store.known_ids()
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
    if want("naver_news"):
        results.append(naver_news.collect(cfg["naver_news"], client, pages=naver_pages, since=since))

    day = now_kst().date().isoformat()
    health = {"day": day, "finished_at": utcnow_iso(), "sources": {}}
    for res in results:
        new = [d for d in res.docs if d["doc_id"] not in known]
        known.update(d["doc_id"] for d in new)
        n = store.append_docs(day, res.source, new) if new else 0
        health["sources"][res.source] = {"ok": res.ok, "seen": len(res.docs), "new": n,
                                         "error": res.error, "note": res.note}
        log.info("%-20s ok=%s seen=%d new=%d %s", res.source, res.ok, len(res.docs), n,
                 res.error or res.note or "")
    store.write_json(f"health/{day}.json", health)
    return health
