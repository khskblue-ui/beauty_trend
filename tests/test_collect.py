from trend.collect.article import extract_body
from trend.collect.naver_news import relevant
from trend.collect.page_diff import extract_links
from trend.collect.rss import parse_feed

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>A &amp; B</title><link>https://x.test/1</link><description>&lt;p&gt;sum&lt;/p&gt;</description>
<dc:date>2026-10-14 17:48:55</dc:date><content:encoded><![CDATA[<p>full body</p>]]></content:encoded></item>
</channel></rss>"""


def test_parse_feed_rss_with_dc_date_and_content():
    it = parse_feed(RSS)[0]
    assert it["title"] == "A & B" and it["summary"] == "sum"
    assert it["date"] == "2026-10-14 17:48:55" and it["content"] == "full body"


def test_rss_relative_links_become_absolute():
    from trend.collect import rss

    class FakeClient:
        def request(self, url, **kw):
            from trend.http import Response
            return Response(url, 200, {}, b"""<rss><channel><item><title>Symrise news</title>
                <link>/newsroom/article/x/</link><pubDate>Tue, 13 Oct 2026 11:36:15 +0200</pubDate>
                </item></channel></rss>""")

    src = {"id": "symrise", "name": "Symrise", "group": "competitor",
           "url": "https://www.symrise.com/newsroom/press-releases/rss.xml"}
    res = rss.collect(src, FakeClient(), set())
    assert res.docs[0]["url"] == "https://www.symrise.com/newsroom/article/x/"


def test_naver_relevance_filter():
    cfg = {"title_any": ["향수", "화장품"], "exclude_any": ["드라마", "향수를 자극"]}
    assert relevant("니치 향수 브랜드 출시", "", cfg)
    assert not relevant("현대차 조향 시스템", "", cfg)
    assert not relevant("향수 가득한 드라마", "", cfg)
    assert not relevant("화장품 아닌 듯", "옛 향수를 자극하는", cfg)


IFRA_CARD = """<article class="c-card-article"><div><span class="tagline">07 October 2026</span>
<h3 class="c-title">IFRA to present the 52nd Amendment</h3><div class="c-text">Two experts will present
on 24 November 2026.</div></div><a href="https://ifrafragrance.org/latest-updates/ifra-news/x52"><span>Read more</span></a>
</article><article><a href="/about">About us page link</a></article>"""


def test_page_diff_uses_card_heading_and_first_date():
    links = extract_links(IFRA_CARD, "https://ifrafragrance.org/",
                          r"^https://ifrafragrance\.org/latest-updates/ifra-news/[^/]+$")
    assert len(links) == 1
    assert links[0]["title"] == "IFRA to present the 52nd Amendment"
    assert links[0]["date"] == "07 October 2026"  # not the event date in the text
    assert "Read more" not in links[0]["summary"]


def test_extract_body_prefers_article_container():
    html = ('<div>menu menu menu</div><article id="article-view-content-div">'
            + "<p>" + "가" * 120 + "</p><p>" + "나" * 120 + "</p></article>")
    body = extract_body(html)
    assert body and body.startswith("가") and "menu" not in body


def test_backfill_list_reads_dates_from_article_pages_and_stops_past_window(monkeypatch):
    from datetime import date
    from trend.collect import backfill

    class R:
        def __init__(self, text): self.text, self.ok, self.status, self.body = text, True, 200, text.encode()

    pages = {
        "https://t.test/list?page=1": '<a href="/news/articleView.html?idxno=3">a</a><a href="/news/articleView.html?idxno=2">b</a>',
        "https://t.test/list?page=2": '<a href="/news/articleView.html?idxno=1">c</a>',
        "https://t.test/list?page=3": '<a href="/news/articleView.html?idxno=0">d</a>',
    }
    arts = {3: "2026-10-05T10:00:00+09:00", 2: "2026-10-01T08:00:00+09:00", 1: "2026-09-29T08:00:00+09:00",
            0: "2026-09-20T08:00:00+09:00"}

    class C:
        calls = []
        def allowed(self, url): return True
        def request(self, url, **kw):
            self.calls.append(url)
            if url in pages:
                return R(pages[url])
            n = int(url.rsplit("=", 1)[1])
            return R(f'<meta property="og:title" content="기사 {n}"><meta property="article:published_time" content="{arts[n]}">')

    monkeypatch.setattr(backfill.store, "save_body", lambda *a: None)
    src = {"id": "t", "name": "T", "group": "kr_trade", "lang": "ko",
           "archive": {"kind": "list", "url": "https://t.test/list?page={page}",
                       "link_pattern": r"articleView\.html\?idxno=\d+$"}}
    c = C()
    res = backfill.collect(src, c, date(2026, 10, 1), date(2026, 10, 15), {})
    assert sorted(d["title"] for d in res.docs) == ["기사 2", "기사 3"]
    assert all(d["collected_via"] == "backfill" for d in res.docs)
    assert "https://t.test/list?page=3" not in c.calls     # page 2 was entirely before the window


def test_clean_body_drops_site_notices_and_footers():
    from trend.collect.article import clean_body
    t = ("잠깐! 현재 Internet Explorer 8이하 버전을 이용중이십니다.\n유씨엘이 바디케어 트렌드북을 발표했다.\n"
         "사업자등록번호: 000 | © 2016 Copyright All Rights Reserved 코스모닝")
    assert clean_body(t) == "유씨엘이 바디케어 트렌드북을 발표했다."


def test_backfill_list_ignores_repeated_sidebar_links(monkeypatch):
    from datetime import date
    from trend.collect import backfill

    class R:
        def __init__(self, text): self.text, self.ok, self.status = text, True, 200

    side = '<a href="/news/articleView.html?idxno=99">popular</a>'
    pages = {f"https://t.test/l?p={i}": side + f'<a href="/news/articleView.html?idxno={i}">x</a>' for i in (1, 2, 3)}
    dates = {99: "2026-10-14T09:00:00+09:00", 1: "2026-10-03T09:00:00+09:00",
             2: "2026-09-20T09:00:00+09:00", 3: "2026-09-10T09:00:00+09:00"}

    class C:
        calls = []
        def allowed(self, url): return True
        def request(self, url, **kw):
            self.calls.append(url)
            if url in pages:
                return R(pages[url])
            n = int(url.rsplit("=", 1)[1])
            return R(f'<meta property="og:title" content="기사 {n}"><meta property="article:published_time" content="{dates[n]}">')

    monkeypatch.setattr(backfill.store, "save_body", lambda *a: None)
    src = {"id": "t", "name": "T", "group": "kr_trade",
           "archive": {"kind": "list", "url": "https://t.test/l?p={page}", "link_pattern": r"idxno=\d+$"}}
    c = C()
    res = backfill.collect(src, c, date(2026, 10, 1), date(2026, 10, 15), {})
    assert sorted(d["title"] for d in res.docs) == ["기사 1", "기사 99"]
    assert c.calls.count("https://t.test/news/articleView.html?idxno=99") == 1   # sidebar opened once
    assert "https://t.test/l?p=3" not in c.calls          # page 2's only new link is before the window


def test_backfill_list_by_day_reads_one_list_per_day(monkeypatch):
    from datetime import date
    from trend.collect import backfill

    class R:
        def __init__(self, text): self.text, self.ok, self.status = text, True, 200

    class C:
        calls = []
        def allowed(self, url): return True
        def request(self, url, **kw):
            self.calls.append(url)
            if "sdate=" in url:
                day = url.split("sdate=")[1][:10]
                return R(f'<a href="/news/articleView.html?idxno={day[-2:]}">x</a>')
            n = url.rsplit("=", 1)[1]
            return R(f'<meta property="og:title" content="기사 {n}"><meta property="article:published_time" content="2026-10-{n}T09:00:00+09:00">')

    monkeypatch.setattr(backfill.store, "save_body", lambda *a: None)
    src = {"id": "t", "name": "T", "group": "kr_trade",
           "archive": {"kind": "list", "url": "https://t.test/l?sdate={day}", "link_pattern": r"idxno=\d+$"}}
    res = backfill.collect(src, C(), date(2026, 10, 1), date(2026, 10, 3), {})
    assert sorted(d["title"] for d in res.docs) == ["기사 01", "기사 02", "기사 03"]


def test_second_collect_run_on_a_day_keeps_the_first_runs_health(monkeypatch, tmp_path):
    from trend import store
    from trend.collect import run as runmod
    from trend.collect import Result
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    store.write_json("health/2026-10-30.json", {"day": "2026-10-30", "sources": {"jangup": {"ok": True, "new": 5}}})
    monkeypatch.setattr(runmod, "now_kst", lambda: __import__("datetime").datetime(2026, 10, 30, 5, 47))
    monkeypatch.setattr(runmod, "load", lambda n: {"rss": [{"id": "mfds_press"}]})
    monkeypatch.setattr(runmod.rss, "collect", lambda src, client, known: Result("mfds_press", True, []))
    h = runmod.run(only={"mfds_press"})
    assert set(h["sources"]) == {"jangup", "mfds_press"}


def test_backfill_by_day_skips_a_failed_day_and_known_url_variants(monkeypatch):
    from datetime import date
    from trend.collect import backfill
    from trend.util import url_key

    class R:
        def __init__(self, text, ok=True): self.text, self.ok, self.status = text, ok, 200 if ok else None

    class C:
        def __init__(self): self.calls = []
        def allowed(self, url): return True
        def request(self, url, **kw):
            self.calls.append(url)
            if "sdate=" in url:
                day = url.split("sdate=")[1][:10]
                if day == "2026-10-02":
                    return R("", ok=False)            # connection reset on one day's list
                return R(f'<a href="https://t.test/news/articleView.html?idxno={day[-2:]}">x</a>')
            n = url.rsplit("=", 1)[1]
            return R(f'<meta property="og:title" content="기사 {n}"><meta property="article:published_time" content="2026-10-{n}T09:00:00+09:00">')

    monkeypatch.setattr(backfill.store, "save_body", lambda *a: None)
    src = {"id": "t", "name": "T", "group": "kr_trade",
           "archive": {"kind": "list", "url": "https://t.test/l?sdate={day}", "link_pattern": r"idxno=\d+$"}}
    # day 01 is stored already under the feed's http:// link
    known = {url_key("http://www.t.test/news/articleView.html?idxno=01"): date(2026, 10, 1)}
    c = C()
    res = backfill.collect(src, c, date(2026, 10, 1), date(2026, 10, 3), known)
    assert [d["title"] for d in res.docs] == ["기사 03"]                 # day 02 failed, day 03 still read
    assert "https://t.test/news/articleView.html?idxno=01" not in c.calls  # not opened again
    assert "list failed: 2026-10-02" in res.note


def test_later_run_on_the_same_day_clears_an_earlier_failure(monkeypatch, tmp_path):
    from trend import store
    from trend.collect import run as runmod
    from trend.collect import Result
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    store.write_json("health/2026-10-30.json", {"day": "2026-10-30", "sources": {
        "thebk": {"ok": False, "seen": 0, "new": 0, "error": "URLError: reset", "note": None}}})
    monkeypatch.setattr(runmod, "now_kst", lambda: __import__("datetime").datetime(2026, 10, 30, 13, 0))
    monkeypatch.setattr(runmod, "load", lambda n: {"rss": [{"id": "thebk"}]})
    doc = {"doc_id": "d1", "url": "https://t.test/1", "source": "thebk"}
    monkeypatch.setattr(runmod.rss, "collect", lambda src, client, known: Result("thebk", True, [doc]))
    h = runmod.run(only={"thebk"})
    assert h["sources"]["thebk"] == {"ok": True, "seen": 1, "new": 1, "error": None, "note": None}
    assert h["this_run"] == {"thebk": True}
    assert "this_run" not in store.read_json(tmp_path / "health" / "2026-10-30.json")


def test_naver_paging_stops_at_the_backfill_window(monkeypatch, tmp_path):
    from datetime import date
    from trend.collect import run as runmod
    from trend.collect import Result
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(runmod, "load", lambda n: {"naver_news": {"queries": []}})
    seen = {}

    def fake(cfg, client, pages=1, since=None):
        seen.update(pages=pages, since=since)
        return Result("naver_news", True, [])
    monkeypatch.setattr(runmod.naver_news, "collect", fake)
    runmod.run(only={"naver_news"}, naver_pages=5, backfill_since=date(2026, 10, 27))
    assert seen == {"pages": 5, "since": date(2026, 10, 27)}
