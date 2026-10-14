"""Weekly collector health check: zero days, sharp drops, failures."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from . import store
from .util import now_kst


QUIET_SOURCES = {"eu_cosmetics_reg", "fda_fedreg", "ifra_news", "mfds_law", "mfds_notice",
                 "mfds_preannounce", "mfds_press", "givaudan", "symrise", "dsm_firmenich"}


def summarize(days: int = 7) -> tuple[str, bool]:
    today = now_kst().date()
    window = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    base = [(today - timedelta(days=i)).isoformat() for i in range(days, days * 5)]
    cur, prev, fails = defaultdict(int), defaultdict(int), defaultdict(list)
    for p in (store.data_dir() / "health").glob("*.json"):
        h = store.read_json(p, {})
        for src, v in h.get("sources", {}).items():
            if h["day"] in window:
                cur[src] += v.get("new", 0)
                if not v.get("ok"):
                    fails[src].append(f"{h['day']}: {v.get('error')}")
            elif h["day"] in base:
                prev[src] += v.get("new", 0)
    lines, alarm = [f"수집기 헬스체크 {window[-1]} ~ {window[0]}"], False
    for src in sorted(set(cur) | set(prev) | set(fails)):
        avg = prev[src] / 4 if prev[src] else None
        flag = ""
        if fails[src]:
            flag = f"실패 {len(fails[src])}회 (최근: {fails[src][-1]})"
        elif cur[src] == 0:
            flag = "신규 0건"
        elif avg and cur[src] < avg * 0.3:
            flag = f"급감 (주평균 {avg:.0f} → {cur[src]})"
        # 규제·경쟁사 소스는 신규 0건이 정상일 수 있어 실패만 경보한다.
        quiet_ok = src in QUIET_SOURCES
        if fails[src] or (flag and not quiet_ok):
            alarm = True
        lines.append(f"- {src}: 신규 {cur[src]}건 {flag}")
    return "\n".join(lines), alarm
