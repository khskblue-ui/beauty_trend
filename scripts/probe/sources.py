"""Source registry for web_probe.py (phase-0 audit).

feeds: RSS/Atom URLs. pages: list pages watched by diffing (no feed).
check_paths: paths evaluated against robots.txt.
Requests per source stay at ~3-6 (robots, home, feeds, one article, pages).
"""

SOURCES = {
    # --- 국내 업계지 ---
    "cosmorning": {"name": "코스모닝", "base": "https://www.cosmorning.com",
                   "check_paths": ["/", "/data/rss/news.xml", "/news/article.html"],
                   "feeds": ["https://www.cosmorning.com/data/rss/news.xml"]},
    "jangup": {"name": "장업신문", "base": "https://www.jangup.com",
               "check_paths": ["/", "/rss/allArticle.xml", "/news/articleView.html"],
               "feeds": ["https://www.jangup.com/rss/allArticle.xml"]},
    "cmn": {"name": "CMN(주간신문씨엠엔)", "base": "https://www.cmn.co.kr",
            "home_url": "https://www.cmn.co.kr/main/",
            "check_paths": ["/", "/rss/", "/sub/news/news_view.asp", "/sub/news/news_list.asp"]},
    "thebk": {"name": "뷰티경제", "base": "https://www.thebk.co.kr",
              "check_paths": ["/", "/rss/", "/news/articleView.html"],
              "feeds": ["https://cdn.thebk.co.kr/rss/gn_rss_allArticle.xml"]},
    "cosinkorea": {"name": "코스인코리아", "base": "https://www.cosinkorea.com",
                   "check_paths": ["/", "/data/rss/news.xml", "/news/article.html"],
                   "feeds": ["https://www.cosinkorea.com/data/rss/news.xml"]},
    # --- 국내 커머스 (robots/차단 여부만 확인, 수집 시도 없음) ---
    "oliveyoung": {"name": "올리브영", "base": "https://www.oliveyoung.co.kr",
                   "home_url": "https://www.oliveyoung.co.kr/store/main/getBestList.do",
                   "check_paths": ["/", "/store/main/getBestList.do",
                                   "/store/main/getNewList.do"]},
    "musinsa": {"name": "무신사뷰티", "base": "https://www.musinsa.com",
                "home_url": "https://www.musinsa.com/main/beauty/ranking",
                "check_paths": ["/", "/main/beauty/ranking", "/ranking"]},
    # --- 글로벌 업계지 ---
    "wwd": {"name": "WWD Beauty", "base": "https://wwd.com",
            "home_url": "https://wwd.com/beauty-industry-news/",
            "check_paths": ["/beauty-industry-news/", "/beauty-industry-news/feed/"],
            "feeds": ["https://wwd.com/beauty-industry-news/feed/"]},
    "cosmeticsbusiness": {"name": "Cosmetics Business",
                          "base": "https://www.cosmeticsbusiness.com",
                          "check_paths": ["/", "/rss"],
                          "feeds": ["https://www.cosmeticsbusiness.com/rss"]},
    "premiumbeautynews": {"name": "Premium Beauty News",
                          "base": "https://www.premiumbeautynews.com",
                          "check_paths": ["/", "/spip.php?page=backend"],
                          "feeds": ["https://www.premiumbeautynews.com/spip.php?page=backend"]},
    "cosmeticsdesign_eu": {"name": "CosmeticsDesign-Europe",
                           "base": "https://www.cosmeticsdesign-europe.com"},
    "cosmeticsdesign_asia": {"name": "CosmeticsDesign-Asia",
                             "base": "https://www.cosmeticsdesign-asia.com"},
    "beautymatter": {"name": "BeautyMatter", "base": "https://beautymatter.com",
                     "check_paths": ["/", "/articles/", "/sitemap.xml"],
                     "pages": ["https://beautymatter.com/sitemap.xml"]},
    "gci": {"name": "Global Cosmetic Industry", "base": "https://www.gcimagazine.com",
            "check_paths": ["/", "/__rss/website-scheduled-content.xml"],
            "feeds": ["https://www.gcimagazine.com/__rss/website-scheduled-content.xml"
                      "?input=%7B%22sectionAlias%22%3A%22home%22%7D"]},
    # --- 규제 ---
    "ifra": {"name": "IFRA", "base": "https://ifrafragrance.org",
             "home": False, "check_paths": ["/latest-updates", "/standards-library"],
             "pages": ["https://ifrafragrance.org/latest-updates/ifra-news",
                       "https://ifrafragrance.org/standards-library"]},
    "eurlex": {"name": "EUR-Lex", "base": "https://eur-lex.europa.eu",
               "home_url": "https://eur-lex.europa.eu/eli/reg/2009/1223/oj"},
    "mfds": {"name": "식약처", "base": "https://www.mfds.go.kr", "home": False,
             "check_paths": ["/", "/www/rss/brd.do"],
             "check_article": False,
             "feeds": ["https://www.mfds.go.kr/www/rss/brd.do?brdId=ntc0021",   # 보도자료
                       "https://www.mfds.go.kr/www/rss/brd.do?brdId=data0005",  # 고시전문
                       "https://www.mfds.go.kr/www/rss/brd.do?brdId=data0009",  # 행정예고
                       "https://www.mfds.go.kr/www/rss/brd.do?brdId=data0008"]},  # 최근 개정 법령
    "fda_mocra": {"name": "FDA MoCRA", "base": "https://www.fda.gov", "home": False,
                  "check_paths": ["/cosmetics/cosmetics-laws-regulations/modernization-cosmetics-regulation-act-2022-mocra",
                                  "/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"],
                  "check_article": False,
                  "feeds": ["https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"],
                  "pages": ["https://www.fda.gov/cosmetics/cosmetics-laws-regulations/modernization-cosmetics-regulation-act-2022-mocra",
                            "https://www.fda.gov/cosmetics/cosmetics-news-events"]},
    # FDA는 러너(Azure) IP에서 404를 반환함 → 미국 규제 변경은 Federal Register로 대체 검토.
    # 짧은 시간에 여러 번 요청하면 IP가 차단되므로 하루 1회만 호출할 것.
    "federal_register": {"name": "Federal Register (FDA, cosmetic product)",
                         "base": "https://www.federalregister.gov", "home": False,
                         "check_article": False,
                         "check_paths": ["/api/v1/documents.rss"],
                         "feeds": ["https://www.federalregister.gov/api/v1/documents.rss"
                                   "?conditions%5Bagencies%5D%5B%5D=food-and-drug-administration"
                                   "&conditions%5Bterm%5D=%22cosmetic+product%22&order=newest"]},
    # --- 경쟁 향료사 ---
    "givaudan": {"name": "Givaudan", "base": "https://www.givaudan.com", "home": False,
                 "check_paths": ["/rss", "/media/media-releases"],
                 "feeds": ["https://www.givaudan.com/rss"]},
    "dsm_firmenich": {"name": "dsm-firmenich", "base": "https://www.dsm-firmenich.com",
                      "home": False,
                      "check_paths": ["/en/home.html"],
                      "pages": ["https://our-company.dsm-firmenich.com/en/our-company/news.html"]},
    "iff": {"name": "IFF", "base": "https://www.iff.com", "home": False,
            "check_paths": ["/", "/news/"],
            "pages": ["https://www.iff.com/news/", "https://ir.iff.com/news-events/press-releases"]},
    "symrise": {"name": "Symrise", "base": "https://www.symrise.com", "home": False,
                "check_paths": ["/newsroom/press-releases", "/newsroom/press-releases/rss.xml"],
                "feeds": ["https://www.symrise.com/newsroom/press-releases/rss.xml"]},
}
