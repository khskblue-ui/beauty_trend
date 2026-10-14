from trend.enrich import check, quote_ok
from trend.gate import evaluate
from trend.normalize import cluster, similar
from trend.verify import static_checks


def rec(did, title, date="2026-09-10T09:00:00+09:00", **ex):
    base = {"relevant": True, "keywords": [], "products": [], "brands": [], "companies": [],
            "key_fact": None, "key_fact_quote": None, "is_press_release": False}
    base.update(ex)
    return {"doc_id": did, "title": title, "summary": "", "published_at": date,
            "source": "s", "source_name": "S", "group": "kr_trade", "lang": "ko",
            "url": f"https://x.test/{did}", "evidence_grade": "article", "extraction": base}


def test_quote_must_be_verbatim_modulo_whitespace():
    text = "딥티크가  무화과와\n시더우드 노트의 향수를 출시했다."
    assert quote_ok("무화과와 시더우드 노트", text)
    assert not quote_ok("무화과·시더우드 노트", text)
    assert not quote_ok(None, text)


def test_check_drops_unquoted_notes_and_dates():
    text = "브랜드 A가 9월 1일 신제품 B를 출시했다. 무화과 노트가 특징이다."
    ex = {"products": [{"name": "B", "brand": "A", "launch_date": "2026-09-01",
                        "launch_quote": "9월 1일 신제품 B를 출시했다", "notes": ["무화과", "장미"],
                        "notes_quote": "무화과 노트가 특징이다"}],
          "key_fact": "x", "key_fact_quote": "없는 인용", "brands": ["A", "Z"]}
    out = check(ex, text)
    p = out["products"][0]
    assert p["launch_date"] == "2026-09-01"
    assert p["notes"] == ["무화과"]          # '장미' is not in the quote
    assert out["key_fact"] is None           # fabricated quote → dropped
    assert out["brands"] == ["A"]


def test_cluster_merges_near_duplicate_titles_within_window():
    docs = [rec("1", "아모레퍼시픽, 신규 향수 브랜드 론칭"),
            rec("2", "아모레퍼시픽 신규 향수 브랜드 론칭", date="2026-09-11T10:00:00+09:00"),
            rec("3", "아모레퍼시픽 신규 향수 브랜드 론칭", date="2026-09-25T10:00:00+09:00"),
            rec("4", "LG생활건강 3분기 실적 발표")]
    cs = cluster(docs)
    assert sorted(len(c.docs) for c in cs) == [1, 1, 2]
    assert similar("니치 향수 출시", "니치 향수 출시!") and not similar("향수", "실적")


def test_static_checks():
    r = rec("1", "브랜드 A, 무화과 향수 출시", brands=["A"])
    recs = {"1": r}
    good = {"text": "브랜드 A가 무화과 향수를 출시했다.", "doc_ids": ["1"], "quote": "브랜드 A, 무화과 향수 출시"}
    assert static_checks(good, {"1"}, recs, {"A", "B사"}) is None
    assert static_checks({**good, "doc_ids": ["9"]}, {"1"}, recs, set()) == "citation"
    assert static_checks({**good, "quote": "지어낸 인용"}, {"1"}, recs, set()) == "quote_not_verbatim"
    assert static_checks({**good, "text": "브랜드 A가 3종을 출시했다."}, {"1"}, recs, set()) == "digits"
    bad_ent = {**good, "text": "B사와 브랜드 A가 향수를 출시했다."}
    assert static_checks(bad_ent, {"1"}, recs, {"A", "B사"}) == "entity:B사"


def test_gate_hides_customer_sections_and_holds_on_core_majority():
    cfg = {"sections": {
        "keywords": {"core": True, "min_clusters_per_item": 2},
        "launches": {"core": True, "min_items": 5},
        "market": {"core": True, "min_items": 3},
        "regulation": {"core": True},
        "customers": {"hidden_without_customers": True}},
        "customers": [], "hold_if_core_failed_ratio": 0.5}
    g = evaluate({"keywords": {"n": 2}, "launches": {"n": 1}, "market": {"n": 4},
                  "regulation": {"n": 0}}, cfg)
    assert g["sections"]["customers"]["status"] == "hidden"
    assert g["sections"]["launches"]["status"] == "reduced"
    assert g["sections"]["regulation"]["status"] == "ok"   # 변경 없음 is valid
    assert not g["hold"]
    g2 = evaluate({"keywords": {"n": 0}, "launches": {"n": 0}, "market": {"n": 4},
                   "regulation": {"n": 1}}, cfg)
    assert not g2["hold"]          # 2/4 is not a majority
    g3 = evaluate({"keywords": {"n": 0}, "launches": {"n": 0}, "market": {"n": 0},
                   "regulation": {"n": 1}}, cfg)
    assert g3["hold"]
