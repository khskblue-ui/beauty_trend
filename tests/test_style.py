"""Style rules (config/style.yaml) for generated sentences and template copy.

If a template edit fails here, rewrite the copy following docs/style_guide.md.
"""
import re

import pytest

from trend.config import ROOT
from trend.style import copy_violations, lint

# Sentences actually generated for 2026-09 before the style pass.
SEPT_BAD = {
    "한미사이언스는 독자 개발한 혁신 복합 원료를 기반으로 피부 본연의 건강함에 집중한 라인업을 선보였다.": "promo",
    "다비디퓨저는 킹고스프링으로부터 투자를 유치하여 글로벌 시장 진출을 가속화했다.": "cliche_verb",
    "LG생활건강은 닥터그루트를 앞세워 멕시코에서 케이뷰티 시장 공략을 본격화했다.": "cliche_verb",
    "심라이즈는 플로럴 콘셉트 인수를 최종 완료하여 천연 원료 분야에서의 입지를 강화했다.": "double_particle",
    "심라이즈는 그라스에 사업장을 마련하고 전략적 투자를 통해 원료 역량을 확대했다.": "tonghae",
    "지보단은 자사의 제품 탄소 발자국 프로그램에 대해 업계 최초로 이중 인증을 획득했다.": "jasa",
    "국제향료협회는 브라질 국가위생감시국과 함께 향료 안전성에 관한 규제 대화를 강화했다.": "translated_verb",
    "국제향료협회는 상하이에서 회원사 리더십 회의를 소집했다.": "translated_verb",
    "에스트라와 라로슈포제 및 닥터지 순으로 브랜드평판 순위가 집계됐다.": "mit",
}

GOOD = [
    "심라이즈는 플로럴 콘셉트 인수를 마쳤다.",
    "국제향료협회는 상하이에서 회원사 경영진 회의를 열었다.",
    "바이레도는 신제품 퓨쳐 메모리즈 출시에 맞춰 성수동에 팝업스토어를 열었다.",
    "무신사 뷰티는 홍대에 첫 단독 매장을 열었다.",
]


@pytest.mark.parametrize("text,rule", SEPT_BAD.items())
def test_lint_catches_september_patterns(text, rule):
    assert rule in {h["id"] for h in lint(text)}


@pytest.mark.parametrize("text", GOOD)
def test_lint_passes_plain_sentences(text):
    assert lint(text) == []


def _visible_copy(path):
    """Reader-facing text of a template: drop CSS, JS, Jinja comments/tags, HTML tags."""
    t = path.read_text("utf-8")
    t = re.sub(r"<style>.*?</style>|<script>.*?</script>", " ", t, flags=re.S)
    t = re.sub(r"\{#.*?#\}", " ", t, flags=re.S)
    t = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    # aria-labels are read aloud, so keep them
    t += " " + " ".join(re.findall(r'aria-label="([^"]*)"', path.read_text("utf-8")))
    # string literals passed to macros (e.g. empty-state messages) are reader-facing too
    t += " " + " ".join(re.findall(r"'([^'<>{}\n]*[가-힣][^'<>{}\n]*)'", path.read_text("utf-8")))
    return re.sub(r"\s+", " ", t)


TEMPLATES = sorted((ROOT / "templates").rglob("*.j2"))


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_copy_has_no_jargon(path):
    assert copy_violations(_visible_copy(path)) == []


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_copy_passes_sentence_rules(path):
    hits = {h["id"] for h in lint(_visible_copy(path))}
    # hype/promo/cliché wording must never appear in fixed copy
    assert not hits & {"hype", "promo", "tonghae", "double_particle", "cliche_verb",
                       "hayeo", "mit", "jasa", "translated_verb", "geot_natanatda"}


def test_polish_rewrites_only_wording(monkeypatch):
    from trend import style
    from trend.llm import Call

    def fake(cfg, prompt, schema, system, ledger):
        return Call("m", {"items": [{"i": 0, "text": "다비디퓨저는 킹고스프링에서 투자를 받았다."}]}, {}, 1)

    monkeypatch.setattr(style, "generate_json", fake)
    s = [{"text": "다비디퓨저는 킹고스프링으로부터 투자를 유치하여 글로벌 시장 진출을 가속화했다.",
          "doc_ids": ["d1"], "quote": "다비디퓨저, 킹고스프링 투자 유치"},
         {"text": "무신사 뷰티는 홍대에 첫 단독 매장을 열었다.", "doc_ids": ["d2"], "quote": "q"}]
    out, log = style.polish(s, ledger=None)
    assert out[0]["text"] == "다비디퓨저는 킹고스프링에서 투자를 받았다."
    assert out[0]["doc_ids"] == ["d1"] and out[0]["quote"] == s[0]["quote"]
    assert out[0]["original"] == s[0]["text"]
    assert out[1] == s[1]                     # clean sentence untouched, no LLM call needed
    assert log[0]["remaining"] == []
