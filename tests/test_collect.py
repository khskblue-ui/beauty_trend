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
