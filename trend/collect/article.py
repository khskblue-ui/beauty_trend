"""Extract the main text of an article page (best effort, no JS)."""
from __future__ import annotations

import re

from ..util import clean_text

# Containers seen on the phase-0 sources (ndsoft CMS and similar).
CONTAINERS = [
    r'<article[^>]*id="article-view-content-div"[^>]*>(.*?)</article>',
    r'<div[^>]*id="article-view-content-div"[^>]*>(.*?)</div>\s*<',
    r'<div[^>]*itemprop="articleBody"[^>]*>(.*?)</div>\s*<',
    r'<div[^>]*class="[^"]*(?:article_txt|news_body|article-body|entry-content)[^"]*"[^>]*>(.*?)</div>\s*<',
]
STRIP = re.compile(r"<(script|style|figure|figcaption|table|iframe)[^>]*>.*?</\1>", re.S | re.I)
# Site notices and footers that the paragraph fallback picks up (seen on cosinkorea, cosmorning)
BOILERPLATE = re.compile(r"Internet Explorer|최신 브라우저|All Rights Reserved|Copyright|사업자등록번호|"
                         r"인터넷신문 등록|청소년보호책임자|무단전재|무단 전재", re.I)


def clean_body(text: str | None) -> str | None:
    """Drop notice/footer lines; returns None when nothing is left."""
    if not text:
        return text
    lines = [ln for ln in text.split("\n") if not BOILERPLATE.search(ln)]
    return "\n".join(lines).strip() or None


def extract_body(html: str, min_chars: int = 200) -> str | None:
    html = STRIP.sub(" ", html)
    for pat in CONTAINERS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            text = clean_body(_paragraphs(m.group(1)) or clean_text(m.group(1))) or ""
            if len(text) >= min_chars:
                return text
    text = clean_body(_paragraphs(html)) or ""
    return text if len(text) >= min_chars else None


def _paragraphs(fragment: str) -> str:
    paras = [clean_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", fragment, re.S | re.I)]
    return "\n".join(p for p in paras if len(p) > 40)
