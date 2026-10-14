"""Probe NAVER API HUB: news search, DataLab search trend, Shopping Insight.

Auth: if NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are set (GitHub Actions), the
X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY headers are attached here.
If not set, no auth header is sent (e.g. a proxy injects them).

Usage: python scripts/probe/naver_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from _http import request, save  # noqa: E402

HOST = "https://naverapihub.apigw.ntruss.com"
COSMETICS_CAT = "50000002"  # 네이버쇼핑 '화장품/미용' cat_id


def auth_headers() -> dict:
    cid, sec = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if cid and sec:
        return {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec}
    return {}


def post(path: str, body: dict):
    return request(HOST + path, "POST",
                   {**auth_headers(), "Content-Type": "application/json"},
                   json.dumps(body).encode())


def summarize(name, r, sample_fn=None):
    out = {"name": name, "url": r.url, "status": r.status, "error": r.error,
           "elapsed_s": round(r.elapsed, 2),
           "resp_headers": {k: v for k, v in r.headers.items()
                            if k.lower().startswith(("x-", "content-type", "ratelimit"))}}
    try:
        data = r.json()
        out["sample"] = sample_fn(data) if (sample_fn and r.status == 200) else data
    except Exception:  # noqa: BLE001
        out["body_head"] = r.text[:500]
    print(f"[{name}] {r.status} {r.error or ''} ({r.elapsed:.2f}s)")
    return out


def main():
    print("auth headers from env:", bool(auth_headers()))
    results = []

    q = urllib.parse.urlencode({"query": "향수", "display": 5, "sort": "date"})
    r = request(f"{HOST}/search/v1/news?{q}", headers=auth_headers())
    results.append(summarize("news_search", r, lambda d: {
        "keys": list(d.keys()), "total": d.get("total"),
        "items": d.get("items", [])[:2]}))

    period = {"startDate": "2026-07-01", "endDate": "2026-09-30", "timeUnit": "month"}
    r = post("/search-trend/v1/search", {**period, "keywordGroups": [
        {"groupName": "향수", "keywords": ["향수"]},
        {"groupName": "니치향수", "keywords": ["니치향수", "니치 향수"]}]})
    results.append(summarize("datalab_search_trend", r, lambda d: d))

    r = post("/shopping/v1/categories", {**period, "category": [
        {"name": "화장품/미용", "param": [COSMETICS_CAT]}]})
    results.append(summarize("shopping_categories", r, lambda d: d))

    r = post("/shopping/v1/category/keywords", {**period, "category": COSMETICS_CAT,
             "keyword": [{"name": "향수", "param": ["향수"]},
                         {"name": "바디미스트", "param": ["바디미스트"]}]})
    results.append(summarize("shopping_category_keywords", r, lambda d: d))

    print("saved:", save("naver_probe.json", results))


if __name__ == "__main__":
    main()
