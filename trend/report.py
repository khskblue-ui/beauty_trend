"""Monthly report: normalize → aggregate → write → verify → gate → render (→ deliver)."""
from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from pathlib import Path

from . import aggregate, gate, render, store, style, verify, write
from .config import load
from .normalize import Entities, cluster, load_month
from .util import kst_date, month_bounds, now_kst, prev_month

log = logging.getLogger(__name__)


def _known_entities(recs: list[dict], ents: Entities) -> set[str]:
    names = set(ents.alias.values())
    for r in recs:
        names.update(r["extraction"].get("brands", []))
        names.update(r["extraction"].get("companies", []))
    return {n for n in names if n and len(n) >= 2}


def coverage(ym: str) -> list[dict]:
    """Per-source collection health within the month (from daily health files)."""
    first, last = month_bounds(ym)
    days = defaultdict(lambda: {"ok_days": 0, "fail_days": 0, "new": 0, "last_error": None})
    for p in sorted((store.data_dir() / "health").glob("*.json")):
        h = store.read_json(p, {})
        d = h.get("day")
        if not d or not (first.isoformat() <= d <= last.isoformat()):
            continue
        for src, v in h.get("sources", {}).items():
            row = days[src]
            row["ok_days" if v.get("ok") else "fail_days"] += 1
            row["new"] += v.get("new", 0)
            if not v.get("ok"):
                row["last_error"] = v.get("error")
    docs = Counter()
    for d in store.iter_raw():
        k = kst_date(d.get("published_at"))
        if k and first <= k <= last:
            docs[d["source"]] += 1
    names = set(days) | set(docs)
    return [{"source": s, **days[s], "docs_in_month": docs.get(s, 0)} for s in sorted(names)]


def build(ym: str, dry_run: bool = False, pdf: bool = True) -> dict:
    cfg = load("report")
    run_dir = store.data_dir() / "reports" / ym / now_kst().strftime("%Y%m%dT%H%M")
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = str(run_dir / "llm_calls.jsonl")

    recs = load_month(ym)
    prev = load_month(prev_month(ym))
    clusters, prev_clusters = cluster(recs), cluster(prev)
    by_id = {r["doc_id"]: r for r in recs}
    ents = Entities()
    known = _known_entities(recs, ents)
    agg = aggregate.run(clusters, prev_clusters, ym)
    vlog: list[dict] = []
    slog: list[dict] = []

    def checked(section: str, sents: list[dict], allowed: set[str]) -> list[dict]:
        # style pass first (wording only), then the full verification on the result
        sents, rows = style.polish(sents, ledger)
        slog.extend({**r, "section": section} for r in rows)
        kept, rows = verify.verify_sentences(sents, allowed, by_id, known, ledger, ents.variants)
        vlog.extend({**r, "section": section} for r in rows)
        return kept

    # keywords
    cid_cards = {c.cid: aggregate._cluster_card(c) for c in clusters}
    kw_items = agg["keywords"]["items"]
    cards_by_term = {it["term"]: [cid_cards[c] for c in it["clusters"][:4]] for it in kw_items}
    kw_sents = write.keyword_notes(kw_items, cards_by_term, ledger)
    # A keyword is a code fact (≥ N distinct clusters); the sentence is only an
    # explanation. Keywords whose sentence fails verification stay, shown with
    # their representative article titles instead.
    kw_kept = []
    for it in kw_items:
        cand = [s for s in kw_sents if s["term"] == it["term"]]
        allowed = {d for c in cards_by_term[it["term"]] for d in c["doc_ids"]}
        ok = checked("keywords", cand, allowed)
        reps = [{"title": c["title"], "doc_id": c["doc_id"]} for c in cards_by_term[it["term"]][:2]]
        kw_kept.append({**it, "sentence": ok[0] if ok else None, "reps": reps})

    # market — skip articles the keyword section already wrote about, so the
    # same news does not appear twice in the report
    kw_used = {d for k in kw_kept if k["sentence"] for d in k["sentence"]["doc_ids"]}
    mk = {}
    for key, task, n in (("kr", "국내 뷰티·향료 시장 동향을 요약한다.", 5),
                         ("global", "글로벌 뷰티·향료 시장 동향을 요약한다. 영어 근거는 한국어로 옮겨 쓴다.", 4)):
        cards = [c for c in agg["market"][key] if not kw_used & set(c["doc_ids"])][:10]
        allowed = {d for c in cards for d in c["doc_ids"]}
        mk[key] = checked(f"market_{key}", write.sentences(task, cards, n, ledger), allowed)

    # regulation & competitors: narrative is optional; the item table is code-generated
    rg = {}
    for key, task in (("regulation", "이번 달 화장품·향료 규제 관련 공지·개정 사항을 정리한다."),
                      ("competitors", "경쟁 향료사(지보단, dsm-firmenich, 심라이즈 등)의 이번 달 발표를 정리한다.")):
        cards = agg["regulation"][key][:10]
        allowed = {d for c in cards for d in c["doc_ids"]}
        rg[key] = checked(key, write.sentences(task, cards, 4, ledger), allowed)

    # 3-line summary: one verified sentence per area (keywords → market → regulation/
    # competitors), skipping any sentence about an article already used.
    summary, used = [], set()
    for pool in ([k["sentence"] for k in kw_kept if k["sentence"]],
                 mk["kr"] + mk["global"], rg["regulation"] + rg["competitors"]):
        pick = next((s for s in pool if not used & set(s["doc_ids"])), None)
        if pick:
            summary.append(pick)
            used |= set(pick["doc_ids"])

    reg_items = agg["regulation"]["regulation"] + agg["regulation"]["competitors"]
    g = gate.evaluate({
        "keywords": {"n": len(kw_kept), "reason_if_low":
                     "서로 다른 보도에서 두 번 이상 다뤄진 키워드가 없습니다"},
        "launches": {"n": len(agg["launches"]), "reason_if_low":
                     f"출시일이 기사로 확인된 신제품이 {len(agg['launches'])}건으로 "
                     f"기준({cfg['sections']['launches']['min_items']}건)보다 적어 목록만 싣습니다"},
        "notes": {"n": agg["notes"]["n"]},
        "market": {"n": len(mk["kr"]) + len(mk["global"]), "reason_if_low":
                   "출처로 확인되는 시장 소식이 기준보다 적습니다"},
        "regulation": {"n": len(reg_items)},
    }, cfg)

    urls = ([c["url"] for c in reg_items] + [x["url"] for x in agg["launches"]]
            + [x["url"] for x in agg["notes"]["items"]]
            + [by_id[d]["url"] for s in summary + mk["kr"] + mk["global"] + rg["regulation"]
               + rg["competitors"] + [k["sentence"] for k in kw_kept if k["sentence"]]
               for d in s["doc_ids"]]
            + [by_id[r["doc_id"]]["url"] for k in kw_kept for r in k["reps"]])
    links = verify.link_status(urls) if os.getenv("SKIP_LINK_CHECK") != "1" else {}

    total = len(vlog)
    kept_n = sum(r["kept"] for r in vlog)
    published = (summary + mk["kr"] + mk["global"] + rg["regulation"] + rg["competitors"]
                 + [k["sentence"] for k in kw_kept if k["sentence"]])
    style_warnings = sorted({(s["text"], h["id"]) for s in published for h in style.lint(s["text"])})
    style_warnings = [{"text": t, "rule": r} for t, r in style_warnings]
    status = "dry_run" if dry_run else ("hold" if g["hold"] else "publish")
    ctx = {
        "cfg": cfg, "month": ym, "generated": now_kst().strftime("%Y-%m-%d %H:%M KST"),
        "status": status, "agg": agg, "gate": g, "summary": summary,
        "keywords": kw_kept, "market": mk, "reg": rg, "by_id": by_id, "links": links,
        "coverage": coverage(ym), "has_prev": bool(prev),
        "verify_stats": {"total": total, "kept": kept_n, "dropped": total - kept_n,
                         "reasons": Counter(r["reason"] for r in vlog if not r["kept"])},
        "models": load("models"),
        "style": {"rewritten": sum(1 for r in slog if r["before"] != r["after"]),
                  "warnings": style_warnings},
    }
    paths = render.render_all(ctx, run_dir, pdf=pdf)

    store.write_json(run_dir.relative_to(store.data_dir()) / "aggregate.json", agg)
    store.write_json(run_dir.relative_to(store.data_dir()) / "verify_log.json", vlog)
    store.write_json(run_dir.relative_to(store.data_dir()) / "gate.json", g)
    store.write_json(run_dir.relative_to(store.data_dir()) / "links.json", links)
    store.write_json(run_dir.relative_to(store.data_dir()) / "style_log.json", slog)
    store.write_json(run_dir.relative_to(store.data_dir()) / "run.json", {
        "month": ym, "status": status, "models": load("models"),
        "prompt_versions": {"write": write.PROMPT_VERSION, "style": style.PROMPT_VERSION},
        "docs": len(recs), "clusters": len(clusters), "prev_docs": len(prev),
        "paths": {k: str(v) for k, v in paths.items()},
        "verify": ctx["verify_stats"], "style": ctx["style"]})

    if os.getenv("DELIVER") == "1":
        from . import deliver
        deliver.send(status, ym, paths, summary, g)
    return {"status": status, "run_dir": str(run_dir), "docs": len(recs),
            "clusters": len(clusters), "gate": {k: v["status"] for k, v in g["sections"].items()},
            "verify": {"total": total, "kept": kept_n},
            "style": {"rewritten": ctx["style"]["rewritten"], "warnings": style_warnings},
            "paths": {k: str(v) for k, v in paths.items()}}
