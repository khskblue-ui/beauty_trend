"""CLI: python -m trend <command>.

  collect [--only a,b] [--since YYYY-MM-DD] [--naver-pages N]
  enrich  [--month YYYY-MM] [--limit N]
  report  --month YYYY-MM [--dry-run]
  render  --run-dir DIR [--no-pdf]   re-render a finished run with current templates (no LLM calls)
  health  [--days 7]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="trend")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--only")
    c.add_argument("--since", type=date.fromisoformat)
    c.add_argument("--naver-pages", type=int, default=1)
    e = sub.add_parser("enrich")
    e.add_argument("--month")
    e.add_argument("--limit", type=int)
    r = sub.add_parser("report")
    r.add_argument("--month", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--no-pdf", action="store_true")
    rr = sub.add_parser("render")
    rr.add_argument("--run-dir", required=True)
    rr.add_argument("--no-pdf", action="store_true")
    h = sub.add_parser("health")
    h.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if a.cmd == "collect":
        from .collect.run import run
        only = set(a.only.split(",")) if a.only else None
        health = run(only, a.naver_pages, a.since)
        failed = [k for k, v in health["sources"].items() if not v["ok"]]
        print(json.dumps({"failed": failed}, ensure_ascii=False))
        return 0
    if a.cmd == "enrich":
        from .enrich import enrich_pending
        print(json.dumps(enrich_pending(a.month, a.limit), ensure_ascii=False))
        return 0
    if a.cmd == "report":
        from .report import build
        out = build(a.month, dry_run=a.dry_run, pdf=not a.no_pdf)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out["status"] != "error" else 1
    if a.cmd == "render":
        from .report import rerender
        paths = rerender(a.run_dir, pdf=not a.no_pdf)
        print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "health":
        from .health import summarize
        text, alarm = summarize(a.days)
        print(text)
        return 2 if alarm else 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
