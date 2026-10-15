"""NAVER DataLab search trend / shopping insight (relative indices, computed in code)."""
from __future__ import annotations

import json

from .collect.naver_news import HOST, auth_headers
from .http import Client
from .util import month_bounds

_client = Client(min_interval=0.3)


def _post(path: str, body: dict) -> dict:
    r = _client.request(HOST + path, "POST",
                        {**auth_headers(), "Content-Type": "application/json"},
                        json.dumps(body, ensure_ascii=False).encode())
    if not r.ok:
        raise RuntimeError(f"datalab {path} {r.status}: {r.text[:200]}")
    return r.json()


def _period(end_ym: str, months: int, until=None) -> tuple[str, str]:
    _, last = month_bounds(end_ym)
    if until:   # interim report: the current month is counted up to `until`
        last = min(last, until)
    y, m = last.year, last.month - months + 1
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}-01", last.isoformat()


def search_trend(terms: list[str], anchor: str, end_ym: str, months: int = 6, until=None) -> dict:
    """Monthly ratios for up to 4 terms + anchor in ONE request (same scale).

    Returns {term: [{period, ratio, vs_anchor}]} where vs_anchor = ratio / anchor ratio.
    """
    start, end = _period(end_ym, months, until)
    groups = [{"groupName": anchor, "keywords": [anchor]}] + [
        {"groupName": t, "keywords": [t]} for t in terms[:4]]
    d = _post("/search-trend/v1/search", {"startDate": start, "endDate": end,
                                          "timeUnit": "month", "keywordGroups": groups})
    series = {r["title"]: {x["period"]: x["ratio"] for x in r["data"]} for r in d["results"]}
    base = series.get(anchor, {})
    out = {}
    for t, s in series.items():
        out[t] = [{"period": p, "ratio": round(v, 2),
                   "vs_anchor": round(v / base[p], 4) if base.get(p) else None}
                  for p, v in sorted(s.items())]
    return {"start": start, "end": end, "anchor": anchor, "series": out}


def shopping_category(category: str, name: str, end_ym: str, months: int = 6, until=None) -> dict:
    start, end = _period(end_ym, months, until)
    d = _post("/shopping/v1/categories", {"startDate": start, "endDate": end, "timeUnit": "month",
                                          "category": [{"name": name, "param": [category]}]})
    return {"start": start, "end": end,
            "series": [{"period": x["period"], "ratio": round(x["ratio"], 2)}
                       for x in d["results"][0]["data"]]}


def shopping_keywords(terms: list[str], category: str, end_ym: str, months: int = 6, until=None) -> dict:
    """Weekly click ratios of up to 5 terms in a shopping category, in ONE request (same scale).

    Ends on the last full week (Sunday) so a half week does not look like a drop.
    `change` = mean of the last 4 weeks / mean of the 4 weeks before - 1 (code-computed).
    """
    from datetime import date, timedelta
    start, end = _period(end_ym, months, until)
    end_d = date.fromisoformat(end)
    end_d -= timedelta(days=(end_d.weekday() + 1) % 7)          # back to Sunday
    d = _post("/shopping/v1/category/keywords", {
        "startDate": start, "endDate": end_d.isoformat(), "timeUnit": "week", "category": category,
        "keyword": [{"name": t, "param": [t]} for t in terms[:5]]})
    series, change = {}, {}
    for r in d["results"]:
        pts = [(x["period"], round(x["ratio"], 2)) for x in r["data"]]
        series[r["title"]] = pts
        vals = [v for _, v in pts]
        if len(vals) >= 8 and sum(vals[-8:-4]):
            change[r["title"]] = round(sum(vals[-4:]) / sum(vals[-8:-4]) - 1, 3)
    return {"start": start, "end": end_d.isoformat(), "series": series, "change": change}
