from trend.config import ROOT, load


def test_all_config_files_parse_with_expected_keys():
    names = [p.stem for p in (ROOT / "config").glob("*.yaml")]
    assert {"models", "sources", "report", "entities"} <= set(names)
    for n in names:
        assert isinstance(load(n), dict), n
    r = load("report")
    assert {"keywords", "launches", "market", "regulation"} <= set(r["sections"])
    assert isinstance(r["keyword_stoplist"], list)
    for stage in ("enrich", "write", "verify"):
        assert load("models")[stage]["model"]


def test_motion_templates_exist_for_configured_variants():
    for v in load("report").get("motion_variants", []):
        assert (ROOT / "templates" / "motion" / f"{v}.html.j2").exists(), v
