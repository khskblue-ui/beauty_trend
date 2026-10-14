"""EU acts amending a base regulation, via the Publications Office SPARQL endpoint.

eur-lex.europa.eu serves an AWS WAF challenge to scripts; CELLAR does not.
"""
from __future__ import annotations

import urllib.parse

from ..http import Client
from ..util import doc_id, parse_date, to_kst_iso, utcnow_iso
from . import Result

ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex ?date ?title WHERE {{
  ?act cdm:resource_legal_amends_resource_legal ?base .
  ?base cdm:resource_legal_id_celex "{base}"^^<http://www.w3.org/2001/XMLSchema#string> .
  ?act cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?act cdm:work_date_document ?date }}
  OPTIONAL {{
    ?expr cdm:expression_belongs_to_work ?act ;
          cdm:expression_title ?title ;
          cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
  }}
}} ORDER BY DESC(?date) LIMIT {limit}
"""


def collect(src: dict, client: Client, limit: int = 20) -> Result:
    q = QUERY.format(base=src["base_celex"], limit=limit)
    r = client.request(ENDPOINT + "?" + urllib.parse.urlencode({"query": q}),
                       headers={"Accept": "application/sparql-results+json"}, timeout=60)
    if not r.ok:
        return Result(src["id"], False, error=r.error or f"HTTP {r.status}")
    docs = []
    for b in r.json()["results"]["bindings"]:
        celex = b["celex"]["value"]
        url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
        published = parse_date(b.get("date", {}).get("value"))
        docs.append({
            "doc_id": doc_id(url), "source": src["id"], "source_name": src["name"],
            "group": src["group"], "lang": "en", "url": url,
            "title": b.get("title", {}).get("value") or f"CELEX {celex}",
            "summary": "", "published_at": to_kst_iso(published), "date_source": "cellar",
            "fetched_at": utcnow_iso(), "evidence_grade": "official", "body_chars": 0,
            "celex": celex,
        })
    return Result(src["id"], True, docs)
