"""Probe 관세청 품목별 국가별 수출입실적(GW) on data.go.kr (HS 3302/3303/3304).

Needs a data.go.kr service key in DATA_GO_KR_SERVICE_KEY (not in this repo).
Without it the script only prints the planned requests and exits.
Spec (data.go.kr/data/15100475): GET /1220000/nitemtrade/getNitemtradeList
  serviceKey, strtYymm, endYymm (<=1 year), hsSgn (optional), cntyCd (required)
Data is refreshed around the 15th of each month, through the previous month.

Usage: python scripts/probe/customs_probe.py [YYYYMM]
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(__file__))
from _http import request, save  # noqa: E402

URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
HS = ["3302", "3303", "3304"]  # 향료 혼합물 / 향수 / 미용·메이크업·기초화장품
COUNTRIES = ["US", "CN", "JP"]  # probe sample only


def main():
    today = dt.date.today()
    default = (today.replace(day=1) - dt.timedelta(days=45)).strftime("%Y%m")
    yymm = sys.argv[1] if len(sys.argv) > 1 else default
    key = os.getenv("DATA_GO_KR_SERVICE_KEY")
    plan = [{"hsSgn": h, "cntyCd": c, "strtYymm": yymm, "endYymm": yymm}
            for h in HS for c in COUNTRIES]
    if not key:
        print("DATA_GO_KR_SERVICE_KEY not set; planned requests:")
        for p in plan:
            print("  GET", URL, p)
        return
    results = []
    for p in plan:
        q = urllib.parse.urlencode({"serviceKey": key, **p})
        r = request(f"{URL}?{q}")
        row = {**p, "status": r.status, "error": r.error}
        try:
            root = ET.fromstring(r.body)
            row["resultCode"] = root.findtext(".//resultCode")
            row["items"] = [{c.tag: c.text for c in it} for it in root.iter("item")]
        except ET.ParseError:
            row["body_head"] = r.text[:300]
        print(p["hsSgn"], p["cntyCd"], r.status, row.get("resultCode"), len(row.get("items", [])))
        results.append(row)
    save("customs_probe.json", results)


if __name__ == "__main__":
    main()
