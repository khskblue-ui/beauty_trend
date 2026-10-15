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


def test_keywords_drop_query_echo_and_generic_terms():
    from trend.aggregate import doc_keywords
    d = rec("1", "t", keywords=["니치 향수", "비건 뷰티", "향수", "우디 향"])
    d["query"] = "니치 향수"
    assert doc_keywords(d, {"향수"}) == {"비건뷰티", "우디향"}   # keys ignore spacing; labels keep the common spelling
    d.pop("query")
    assert "니치향수" in doc_keywords(d, {"향수"})   # trade press: no query bias


def test_same_product_merges_name_variants_of_same_brand_only():
    from trend.aggregate import same_product
    a = {"brand": "겔랑", "name": "뢰르 블루"}
    assert same_product(a, {"brand": "겔랑", "name": "뢰르 블루 오 드 퍼퓸"})
    assert not same_product(a, {"brand": "샤넬", "name": "뢰르 블루"})
    assert not same_product(a, {"brand": "겔랑", "name": "샬리마"})


def test_entity_check_accepts_alias_spelling():
    from trend.normalize import Entities
    r = rec("1", "Symrise completes acquisition of Floral Concept", companies=["Symrise"])
    s = {"text": "심라이즈는 플로럴 콘셉트 인수를 완료했다.", "doc_ids": ["1"],
         "quote": "Symrise completes acquisition of Floral Concept"}
    ents = Entities()
    assert static_checks(s, {"1"}, {"1": r}, {"심라이즈"}) == "entity:심라이즈"
    assert static_checks(s, {"1"}, {"1": r}, {"심라이즈"}, ents.variants) is None


def test_duplicate_sentence_threshold_separates_september_pairs():
    from trend.report import DUP_SENTENCE
    kw = "한미사이언스는 자체 개발한 복합 원료를 적용해 인공색소와 향료를 넣지 않은 제품군을 선보였다."
    dup = "한미사이언스가 개발한 복합 원료로 인공색소와 향료를 배제한 고기능성 제품을 선보이고 있다."
    other = "다비디퓨저는 킹고스프링에서 투자를 유치하고 글로벌 시장에 진출한다."
    assert similar(kw, dup, DUP_SENTENCE) and not similar(kw, other, DUP_SENTENCE)


def _prod(name, brand="브랜드A", status="launched", ld=None, quote="신제품을 출시했다"):
    return {"name": name, "brand": brand, "launch_date": ld, "launch_status": status,
            "launch_quote": quote, "notes": [], "notes_quote": None}


def test_launches_use_publish_date_when_article_reports_launch_without_date():
    from datetime import date
    from trend.aggregate import launches
    from trend.normalize import Entities
    docs = [rec("1", "브랜드A 향수 X 출시", date="2026-10-05T09:00:00+09:00", products=[_prod("X")]),
            rec("2", "브랜드A 향수 Y 출시 예정", date="2026-10-06T09:00:00+09:00",
                products=[_prod("Y", status="upcoming")]),
            rec("3", "판매 순위", date="2026-10-07T09:00:00+09:00", products=[_prod("Z", status="unknown")]),
            rec("4", "브랜드A 향수 W 출시", date="2026-10-20T09:00:00+09:00", products=[_prod("W")]),
            rec("5", "브랜드A 향수 X 10월 2일 출시", date="2026-10-08T09:00:00+09:00",
                products=[_prod("X", ld="2026-10-02")])]
    out = launches(cluster(docs), "2026-10", Entities(), until=date(2026, 10, 15))
    got = {x["name"]: (x["launch_date"], x["date_basis"]) for x in out}
    # stated date wins over the publish-date stand-in; upcoming/unknown and after `until` drop
    assert got == {"X": ("2026-10-02", "article")}
    docs[4]["extraction"]["products"] = []
    out = launches(cluster(docs), "2026-10", Entities(), until=date(2026, 10, 15))
    assert [(x["name"], x["launch_date"], x["date_basis"]) for x in out] == [("X", "2026-10-05", "published")]


def test_check_resets_launch_status_without_verbatim_quote():
    ex = {"products": [_prod("B", quote="지어낸 문장")], "key_fact": None, "key_fact_quote": None,
          "brands": []}
    p = check(ex, "브랜드A가 B를 소개했다.")["products"][0]
    assert p["launch_status"] == "unknown" and p["launch_quote"] is None


def test_regulation_keeps_official_sources_only():
    from trend.aggregate import regulation
    docs = [dict(rec("1", "식약처 화장품 고시 개정"), group="regulation", source="mfds_notice"),
            dict(rec("2", "IFRA news update"), group="regulation", source="ifra_news"),
            dict(rec("3", "Symrise acquires"), group="competitor", source="symrise")]
    out = regulation(cluster(docs), ["mfds_notice"])
    assert [c["title"] for c in out["regulation"]] == ["식약처 화장품 고시 개정"]
    assert out["competitors"] == []


def test_interim_period():
    from datetime import date
    from trend.render import with_period
    from trend.report import period
    p = period("2026-10", date(2026, 10, 15))
    assert p == {"start": "2026-10-01", "end": "2026-10-15", "interim": True}
    assert period("2026-09", date(2026, 10, 1))["interim"] is False
    ctx = with_period({"month": "2026-10", "period": p})
    assert ctx["period"]["span"] == "10월 1~15일" and ctx["period"]["tag"] == "2026-10 중간"
    assert with_period({"month": "2026-09"})["period"]["end"] == "2026-09-30"


def test_press_release_goes_to_regulation_only_when_classified_regulation():
    from trend.aggregate import market, regulation
    base = dict(group="regulation", source="mfds_press", lang="ko")
    docs = [dict(rec("1", "화장품 안전기준 고시 개정 예고", event_type="regulation"), **base),
            dict(rec("2", "3분기 화장품 수출 역대 최대", event_type="market_trend", key_fact="수출 증가",
                     key_fact_quote="q"), **base)]
    cl = cluster(docs)
    assert [c["title"] for c in regulation(cl, ["mfds_press"])["regulation"]] == ["화장품 안전기준 고시 개정 예고"]
    assert [c["title"] for c in market(cl)["kr"]] == ["3분기 화장품 수출 역대 최대"]


def test_product_rows_need_brand_in_article_and_entailment(monkeypatch):
    from trend import verify
    seen = []

    def fake(pairs, ledger):
        seen.extend(pairs)
        return ["supported" if "베르가못" in claim else "uncertain" for claim, _ in pairs]

    monkeypatch.setattr(verify, "entailment", fake)
    monkeypatch.setattr("trend.enrich.store.load_body", lambda d: None)
    r = rec("1", "딥티크 신제품 오르페옹 출시")
    r["summary"] = "딥티크 오르페옹은 베르가못과 시더 노트로 구성됐다."
    recs = {"1": r}
    items = [{"brand": "", "name": "오르페옹", "notes": ["베르가못"], "doc_id": "1", "quote": "q"},
             {"brand": "바이레도", "name": "오르페옹", "notes": ["베르가못"], "doc_id": "1", "quote": "q"},
             {"brand": "딥티크", "name": "오르페옹", "notes": ["베르가못"], "doc_id": "1",
              "quote": "베르가못과 시더 노트"},
             {"brand": "딥티크", "name": "오르페옹", "notes": ["장미"], "doc_id": "1", "quote": "q"}]
    kept, rows = verify.verify_products(items, "notes", recs, ledger=None)
    assert [k["notes"] for k in kept] == [["베르가못"]]
    assert [r_["reason"] for r_ in rows] == ["no_brand", "brand_not_in_article", None, "entailment:uncertain"]
    assert "딥티크 오르페옹은 베르가못" in seen[0][1]        # evidence includes the article text


def test_citation_anchors_are_unique_and_link_back():
    from trend.render import Citations
    c = Citations({"a": {}, "b": {}})
    first, second = str(c(["a"])), str(c(["a", "b"]))
    assert 'id="cite-1-1"' in first and 'id="cite-1-2"' in second and 'id="cite-2-1"' in second


def test_launch_groups_keep_all_fragrance_and_rank_others_by_trade_press():
    from trend.aggregate import launch_groups
    items = ([{"name": f"F{i}", "category": "fragrance", "group": "kr_news", "launch_date": "2026-10-01"} for i in range(3)]
             + [{"name": "N", "category": "skincare", "group": "kr_news", "n_sources": 1, "launch_date": "2026-10-02"},
                {"name": "T", "category": "makeup", "group": "kr_trade", "n_sources": 1, "launch_date": "2026-10-05"},
                {"name": "M", "category": "skincare", "group": "kr_news", "n_sources": 3, "launch_date": "2026-10-03"}])
    g = launch_groups(items, other_max=2)
    assert len(g["fragrance"]) == 3
    assert [x["name"] for x in g["other"]] == ["M", "T"]      # trade press and wide coverage first, shown by date
    assert g["other_total"] == 3 and g["by_category_text"] == "스킨케어 2개, 메이크업 1개"
