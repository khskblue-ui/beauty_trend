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


def extract_body(html: str, min_chars: int = 200) -> str | None:
    html = STRIP.sub(" ", html)
    for pat in CONTAINERS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            text = _paragraphs(m.group(1)) or clean_text(m.group(1))
            if len(text) >= min_chars:
                return text
    text = _paragraphs(html)
    return text if len(text) >= min_chars else None


def _paragraphs(fragment: str) -> str:
    paras = [clean_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", fragment, re.S | re.I)]
    return "\n".join(p for p in paras if len(p) > 40)
