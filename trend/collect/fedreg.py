"""Federal Register documents for FDA (replaces fda.gov, which 404s from CI IPs).

The API blocks IPs that send bursts; call it once per run.
"""
from __future__ import annotations

import urllib.parse
from datetime import date, timedelta

from ..http import Client
from ..util import clean_text, doc_id, parse_date, to_kst_iso, utcnow_iso
from . import Result

API = "https://www.federalregister.gov/api/v1/documents.json"


def collect(src: dict, client: Client, since: date | None = None) -> Result:
    since = since or date.today() - timedelta(days=45)
    params = [("conditions[agencies][]", src["agency"]), ("conditions[term]", src["term"]),
              ("conditions[publication_date][gte]", since.isoformat()),
              ("order", "newest"), ("per_page", "50")]
    for f in ("title", "abstract", "html_url", "publication_date", "type", "document_number"):
        params.append(("fields[]", f))
    r = client.request(API + "?" + urllib.parse.urlencode(params), retries=0, timeout=45)
    if not r.ok:
        return Result(src["id"], False, error=r.error or f"HTTP {r.status}: {r.text[:120]}")
    docs = []
    for x in r.json().get("results", []):
        published = parse_date(x["publication_date"], "America/New_York")
        docs.append({
            "doc_id": doc_id(x["html_url"]), "source": src["id"], "source_name": src["name"],
            "group": src["group"], "lang": "en", "url": x["html_url"],
            "title": clean_text(x["title"]), "summary": clean_text(x.get("abstract"))[:600],
            "published_at": to_kst_iso(published), "date_source": "api",
            "fetched_at": utcnow_iso(), "evidence_grade": "official", "body_chars": 0,
            "doc_type": x.get("type"),
        })
    return Result(src["id"], True, docs)
