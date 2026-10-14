"""quality gate: per-section minimums → ok / reduced (with reason) / hidden; hold rule."""
from __future__ import annotations


def evaluate(sections: dict, cfg: dict) -> dict:
    """sections: name → {"n": usable item count, "reason_if_low": str, ...}."""
    out, core_failed, core_total = {}, 0, 0
    for name, scfg in cfg["sections"].items():
        s = sections.get(name, {})
        if scfg.get("hidden_without_customers") and not cfg.get("customers"):
            out[name] = {"status": "hidden", "reason": "고객사 목록 미수신"}
            continue
        minimum = scfg.get("min_items", 1)
        if name == "keywords":
            minimum = 1  # each keyword already needs ≥ min_clusters_per_item clusters
        if name == "notes":
            minimum = 1
        n = s.get("n", 0)
        status = "ok" if n >= minimum else "reduced"
        reason = None if status == "ok" else (
            s.get("reason_if_low") or f"확인된 항목이 {n}건으로 기준({minimum}건)에 못 미칩니다")
        if name == "regulation" and n == 0:
            status, reason = "ok", None  # "변경 없음" is a valid result
        out[name] = {"status": status, "reason": reason, "n": n, "min": minimum}
        if scfg.get("core"):
            core_total += 1
            core_failed += status != "ok"
    hold = core_total > 0 and core_failed / core_total > cfg["hold_if_core_failed_ratio"]
    return {"sections": out, "core_failed": core_failed, "core_total": core_total, "hold": hold}
