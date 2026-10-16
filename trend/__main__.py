"""CLI: python -m trend <command>.

  collect [--only a,b] [--since YYYY-MM-DD] [--naver-pages N] [--backfill-since YYYY-MM-DD]
  enrich  [--month YYYY-MM] [--limit N] [--upgrade] [--workers N] [--yes]
  check-products [--month YYYY-MM]   daily: verdicts for new notes/launch claims (bodies on disk)
  llm pending|export|import         session backend: list, hand out and take back model work
  deliver --run-dir DIR             mail a finished run (Actions, after the session commits it)
  usage   [--since YYYY-MM-DD]   LLM tokens and estimated cost per billing day (US Pacific) and model
  report  --month YYYY-MM [--dry-run] [--until YYYY-MM-DD]   --until inside the month = interim report
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
    c.add_argument("--backfill-since", type=date.fromisoformat,
                   help="also read source archives back to this day (feeds keep only a few days)")
    e = sub.add_parser("enrich")
    e.add_argument("--month")
    e.add_argument("--limit", type=int)
    e.add_argument("--upgrade", action="store_true", help="redo docs enriched with an older prompt")
    e.add_argument("--workers", type=int, default=4)
    e.add_argument("--yes", action="store_true", help="run even when the cost estimate is above confirm_over_krw")
    r = sub.add_parser("report")
    r.add_argument("--month", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--no-pdf", action="store_true")
    r.add_argument("--until", type=date.fromisoformat)
    rr = sub.add_parser("render")
    rr.add_argument("--run-dir", required=True)
    rr.add_argument("--no-pdf", action="store_true")
    cp = sub.add_parser("check-products")
    cp.add_argument("--month")
    lm = sub.add_parser("llm")
    lm.add_argument("action", choices=["pending", "export", "import"])
    lm.add_argument("--role", choices=["enrich", "write", "verify"])
    lm.add_argument("--out")
    lm.add_argument("--file")
    lm.add_argument("--by", help="name of the agent that wrote the answers (verify: must start with 'verifier')")
    lm.add_argument("--limit", type=int)
    dl = sub.add_parser("deliver")
    dl.add_argument("--run-dir", required=True)
    u = sub.add_parser("usage")
    u.add_argument("--since")
    h = sub.add_parser("health")
    h.add_argument("--days", type=int, default=7)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if a.cmd == "collect":
        from .collect.run import run
        only = set(a.only.split(",")) if a.only else None
        health = run(only, a.naver_pages, a.since, a.backfill_since)
        failed = [k for k, v in health["sources"].items() if not v["ok"]]
        print(json.dumps({"failed": failed}, ensure_ascii=False))
        return 0
    if a.cmd == "enrich":
        from .enrich import enrich_pending
        print(json.dumps(enrich_pending(a.month, a.limit, a.workers, a.upgrade, a.yes), ensure_ascii=False))
        return 0
    if a.cmd == "report":
        from .report import build
        out = build(a.month, dry_run=a.dry_run, pdf=not a.no_pdf, until=a.until)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return {"error": 1, "pending": 3}.get(out["status"], 0)
    if a.cmd == "render":
        from .report import rerender
        paths = rerender(a.run_dir, pdf=not a.no_pdf)
        print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "check-products":
        from .normalize import load_month
        from .verify import check_products
        from .util import now_kst
        month = a.month or f"{now_kst():%Y-%m}"
        from . import store
        out = check_products(load_month(month), str(store.data_dir() / "llm_ledger" / f"{now_kst():%Y-%m}.jsonl"))
        print(json.dumps(out, ensure_ascii=False))
        return 3 if out["waiting_for_answers"] else 0
    if a.cmd == "llm":
        from pathlib import Path
        from . import exchange
        if a.action == "pending":
            reqs = exchange.open_requests(a.role)
            from collections import Counter
            print(json.dumps({"open": len(reqs), "by_role": Counter(r["role"] for r in reqs)}, ensure_ascii=False))
            return 0
        if a.action == "export":
            n = exchange.export(a.role, Path(a.out), a.limit)
            print(json.dumps({"exported": n, "file": a.out}, ensure_ascii=False))
            return 0
        out = exchange.import_answers(Path(a.file), a.by or "")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 1 if out["rejected"] else 0
    if a.cmd == "deliver":
        from .report import deliver_run
        print(json.dumps(deliver_run(a.run_dir), ensure_ascii=False))
        return 0
    if a.cmd == "usage":
        from .usage import summarize
        print(summarize(a.since))
        return 0
    if a.cmd == "health":
        from .health import summarize
        text, alarm = summarize(a.days)
        print(text)
        return 2 if alarm else 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
