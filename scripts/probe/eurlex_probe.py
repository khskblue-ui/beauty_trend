"""Probe EU Cosmetics Regulation changes via the Publications Office CELLAR
SPARQL endpoint (keyless). eur-lex.europa.eu itself serves an AWS WAF
challenge to scripted clients, so change detection goes through CELLAR.

Lists acts that amend Regulation (EC) No 1223/2009 (CELEX 32009R1223),
newest first. A new CELEX id appearing = regulatory change to report.

Usage: python scripts/probe/eurlex_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from _http import request, save  # noqa: E402

ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex ?date ?title WHERE {
  ?act cdm:resource_legal_amends_resource_legal ?base .
  ?base cdm:resource_legal_id_celex "32009R1223"^^<http://www.w3.org/2001/XMLSchema#string> .
  ?act cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?act cdm:work_date_document ?date }
  OPTIONAL {
    ?expr cdm:expression_belongs_to_work ?act ;
          cdm:expression_title ?title ;
          cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
  }
} ORDER BY DESC(?date) LIMIT 10
"""


def main():
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": QUERY})
    r = request(url, headers={"Accept": "application/sparql-results+json"}, timeout=60)
    print("status:", r.status, r.error or "", f"({r.elapsed:.1f}s)")
    rows = []
    if r.status == 200:
        for b in r.json()["results"]["bindings"]:
            rows.append({k: v["value"] for k, v in b.items()})
        for row in rows:
            print(row.get("date"), row["celex"], (row.get("title") or "")[:110])
    save("eurlex_probe.json", {"status": r.status, "error": r.error,
                               "amending_acts": rows,
                               "eurlex_link_pattern":
                                   "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"})


if __name__ == "__main__":
    main()
